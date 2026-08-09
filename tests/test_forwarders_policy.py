"""Unit tests for webui/forwarders/policy.py - the skip-gates, dispatch, and
failure-escalation logic, independent of *when* any of it runs (that's
webui/scheduler.py, covered by tests/test_scheduler.py instead)."""

from webui.forwarders import policy


def test_serialize_location_round_trips_as_json():
    import json

    location = {"is_semantic": False, "latitude": 1.0, "longitude": 2.0, "time": 1}
    assert json.loads(policy._serialize_location(location)) == location


def test_serialize_location_falls_back_to_str_for_unserializable_values():
    class Weird:
        def __str__(self):
            return "weird-value"

    payload = policy._serialize_location({"thing": Weird()})
    assert "weird-value" in payload


def _traccar_endpoint(**overrides) -> dict:
    endpoint = {
        "type": "traccar", "method": "GET", "url": "http://x/",
        "params": {"id": "{{device_id}}", "lat": "{{latitude}}", "lon": "{{longitude}}"},
        "headers": {}, "body_type": "none", "body": "",
        "variables": {"device_id": "d1"},
    }
    endpoint.update(overrides)
    return endpoint


def test_forward_one_dispatches_via_the_generic_custom_forwarder():
    location = {"is_semantic": False, "latitude": 1.0, "longitude": 2.0, "time": 1}

    # blank url -> httpx never even gets a chance to run, and forward_to_custom
    # reports it as a no-op rather than an error.
    status = policy._forward_one({"method": "GET", "url": "", "params": {}, "headers": {}, "body_type": "none", "body": "", "variables": {}}, location)
    assert status == "skipped"

    # an unroutable host raises inside httpx - that surfaces as an error status.
    unroutable = _traccar_endpoint(url="http://127.0.0.1:9/")
    status = policy._forward_one(unroutable, location)
    assert status.startswith("error:")


def test_endpoint_target_uses_the_method_and_url():
    target = policy._endpoint_target({"method": "GET", "url": "http://y/p1"})
    assert target == "GET http://y/p1"
    assert policy._endpoint_target({}) == "GET"


def test_endpoint_target_is_prefixed_with_alias_when_set():
    target = policy._endpoint_target({"method": "GET", "url": "http://y/p1", "alias": "My phone"})
    assert target == "My phone (GET http://y/p1)"


def test_record_forward_result_resets_streak_on_success():
    endpoint_cfg = {"consecutive_failures": 2}
    location = {"latitude": 1.0, "longitude": 2.0, "time": 5}

    policy._record_forward_result(endpoint_cfg, "ok", location, "Test", now_ts=100)

    assert endpoint_cfg["last_forward_status"] == "ok"
    assert endpoint_cfg["last_forward_time"] == 100
    assert endpoint_cfg["last_sent_lat"] == 1.0
    assert endpoint_cfg["last_sent_lon"] == 2.0
    assert endpoint_cfg["last_sent_fix_time"] == 5
    assert endpoint_cfg["consecutive_failures"] == 0


def test_record_forward_result_counts_consecutive_failures_but_not_skips():
    endpoint_cfg = {"method": "GET", "url": "http://x/"}

    policy._record_forward_result(endpoint_cfg, "skipped: moved less than 50m", None, "Test", now_ts=1)
    assert "consecutive_failures" not in endpoint_cfg  # skips don't start (or break) a failure streak

    policy._record_forward_result(endpoint_cfg, "error: boom", None, "Test", now_ts=2)
    assert endpoint_cfg["consecutive_failures"] == 1

    policy._record_forward_result(endpoint_cfg, "skipped: not updated in the last 30m", None, "Test", now_ts=3)
    assert endpoint_cfg["consecutive_failures"] == 1  # unchanged by the skip in between

    policy._record_forward_result(endpoint_cfg, "error: boom again", None, "Test", now_ts=4)
    assert endpoint_cfg["consecutive_failures"] == 2


def test_record_forward_result_escalates_at_the_threshold(caplog):
    endpoint_cfg = {"method": "GET", "url": "http://x/", "alias": "My server"}

    with caplog.at_level("ERROR", logger="webui.forwarders.policy"):
        for _ in range(policy.FORWARD_FAILURE_ESCALATION_THRESHOLD - 1):
            policy._record_forward_result(endpoint_cfg, "error: boom", None, "Test")
        assert not caplog.records  # not yet at the threshold

        policy._record_forward_result(endpoint_cfg, "error: boom", None, "Test")
        assert len(caplog.records) == 1
        assert "My server" in caplog.records[0].message
        assert "Test" in caplog.records[0].message

        # keeps failing past the threshold -> escalates again at the next multiple, not every time
        for _ in range(policy.FORWARD_FAILURE_ESCALATION_THRESHOLD - 1):
            policy._record_forward_result(endpoint_cfg, "error: boom", None, "Test")
        assert len(caplog.records) == 1

        policy._record_forward_result(endpoint_cfg, "error: boom", None, "Test")
        assert len(caplog.records) == 2


def test_too_close_to_bother_requires_the_toggle_and_a_prior_position():
    location = {"is_semantic": False, "latitude": 45.0, "longitude": 9.0}

    # toggle off -> never skip, regardless of distance
    assert policy._too_close_to_bother(
        {"skip_if_close": False, "last_sent_lat": 45.0, "last_sent_lon": 9.0}, location,
    ) is False

    # toggle on but nothing sent yet -> never skip the first fix
    assert policy._too_close_to_bother({"skip_if_close": True}, location) is False

    # toggle on, within the default threshold of the last sent position -> skip
    assert policy._too_close_to_bother(
        {"skip_if_close": True, "last_sent_lat": 45.0, "last_sent_lon": 9.0}, location,
    ) is True

    # toggle on, well outside the threshold -> don't skip
    far_location = {"is_semantic": False, "latitude": 46.0, "longitude": 9.0}
    assert policy._too_close_to_bother(
        {"skip_if_close": True, "last_sent_lat": 45.0, "last_sent_lon": 9.0}, far_location,
    ) is False

    # semantic locations carry no coordinates - this check never applies to them
    assert policy._too_close_to_bother(
        {"skip_if_close": True, "last_sent_lat": 45.0, "last_sent_lon": 9.0},
        {"is_semantic": True, "latitude": None},
    ) is False


def test_stale_duplicate_requires_the_toggle_and_a_prior_send():
    now = 1_000_000.0
    stale_time = now - policy.FRESH_FIX_AGE_S - 1  # just past the "live" cutoff
    stale_location = {"is_semantic": False, "time": stale_time}

    # toggle off -> never skip, regardless of staleness
    assert policy._stale_duplicate(
        {"skip_if_stale": False, "last_sent_fix_time": stale_time}, stale_location, now=now,
    ) is False

    # toggle on but nothing sent yet -> never skip the first fix
    assert policy._stale_duplicate({"skip_if_stale": True}, stale_location, now=now) is False

    # toggle on, same stale fix time as last sent (within the default gap) -> skip
    assert policy._stale_duplicate(
        {"skip_if_stale": True, "last_sent_fix_time": stale_time}, stale_location, now=now,
    ) is True

    # toggle on, well outside the update gap -> don't skip
    older_last_sent = stale_time - (policy.DEFAULT_MIN_UPDATE_GAP_M * 60) - 1
    assert policy._stale_duplicate(
        {"skip_if_stale": True, "last_sent_fix_time": older_last_sent}, stale_location, now=now,
    ) is False

    # a genuinely live/fresh fix always bypasses the gate
    fresh_location = {"is_semantic": False, "time": now - 1}
    assert policy._stale_duplicate(
        {"skip_if_stale": True, "last_sent_fix_time": stale_time}, fresh_location, now=now,
    ) is False

    # semantic locations carry no fix time - this check never applies to them
    assert policy._stale_duplicate(
        {"skip_if_stale": True, "last_sent_fix_time": stale_time},
        {"is_semantic": True, "time": None}, now=now,
    ) is False


def test_forward_one_reports_stale_duplicate_skip_without_dispatching(monkeypatch):
    dispatched = []
    monkeypatch.setattr(policy, "_dispatch_forward", lambda cfg, loc, name="": dispatched.append(loc) or "ok")

    now = 1_000_000.0
    stale_time = now - policy.FRESH_FIX_AGE_S - 1
    endpoint_cfg = _traccar_endpoint(skip_if_stale=True, min_update_gap_m=10, last_sent_fix_time=stale_time)

    duplicate_location = {"is_semantic": False, "time": stale_time, "latitude": 1.0, "longitude": 2.0}
    monkeypatch.setattr(policy.time, "time", lambda: now)
    assert policy._forward_one(endpoint_cfg, duplicate_location) == "skipped: not updated in the last 10m"
    assert dispatched == []  # the network dispatch was never reached

    fresh_location = {"is_semantic": False, "time": now - 1, "latitude": 1.0, "longitude": 2.0}
    assert policy._forward_one(endpoint_cfg, fresh_location) == "ok"


def test_forward_one_reports_distance_skip_without_dispatching(monkeypatch):
    dispatched = []
    monkeypatch.setattr(policy, "_dispatch_forward", lambda cfg, loc, name="": dispatched.append(loc) or "ok")

    endpoint_cfg = _traccar_endpoint(skip_if_close=True, min_movement_m=100, last_sent_lat=45.0, last_sent_lon=9.0)

    close_location = {"is_semantic": False, "latitude": 45.0, "longitude": 9.0}
    assert policy._forward_one(endpoint_cfg, close_location) == "skipped: moved less than 100m"
    assert dispatched == []  # the network dispatch was never reached

    far_location = {"is_semantic": False, "latitude": 46.0, "longitude": 9.0}
    assert policy._forward_one(endpoint_cfg, far_location) == "ok"
    assert dispatched == [far_location]
