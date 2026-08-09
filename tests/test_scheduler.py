import asyncio
from datetime import datetime

from webui import scheduler


def test_next_run_computes_next_cron_occurrence():
    base = datetime(2026, 8, 6, 12, 0, 0)
    assert scheduler._next_run("*/5 * * * *", base) == datetime(2026, 8, 6, 12, 5, 0)
    assert scheduler._next_run("* * * * *", base) == datetime(2026, 8, 6, 12, 1, 0)


def test_next_run_returns_none_for_invalid_cron():
    assert scheduler._next_run("not-a-cron", datetime.now()) is None


def test_serialize_location_round_trips_as_json():
    import json

    location = {"is_semantic": False, "latitude": 1.0, "longitude": 2.0, "time": 1}
    assert json.loads(scheduler._serialize_location(location)) == location


def test_serialize_location_falls_back_to_str_for_unserializable_values():
    class Weird:
        def __str__(self):
            return "weird-value"

    payload = scheduler._serialize_location({"thing": Weird()})
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
    status = scheduler._forward_one({"method": "GET", "url": "", "params": {}, "headers": {}, "body_type": "none", "body": "", "variables": {}}, location)
    assert status == "skipped"

    # an unroutable host raises inside httpx - that surfaces as an error status.
    unroutable = _traccar_endpoint(url="http://127.0.0.1:9/")
    status = scheduler._forward_one(unroutable, location)
    assert status.startswith("error:")


def test_endpoint_target_uses_the_method_and_url():
    target = scheduler._endpoint_target({"method": "GET", "url": "http://y/p1"})
    assert target == "GET http://y/p1"
    assert scheduler._endpoint_target({}) == "GET"


def test_endpoint_target_is_prefixed_with_alias_when_set():
    target = scheduler._endpoint_target({"method": "GET", "url": "http://y/p1", "alias": "My phone"})
    assert target == "My phone (GET http://y/p1)"


def test_record_forward_result_resets_streak_on_success():
    endpoint_cfg = {"consecutive_failures": 2}
    location = {"latitude": 1.0, "longitude": 2.0, "time": 5}

    scheduler._record_forward_result(endpoint_cfg, "ok", location, "Test", now_ts=100)

    assert endpoint_cfg["last_forward_status"] == "ok"
    assert endpoint_cfg["last_forward_time"] == 100
    assert endpoint_cfg["last_sent_lat"] == 1.0
    assert endpoint_cfg["last_sent_lon"] == 2.0
    assert endpoint_cfg["last_sent_fix_time"] == 5
    assert endpoint_cfg["consecutive_failures"] == 0


def test_record_forward_result_counts_consecutive_failures_but_not_skips():
    endpoint_cfg = {"method": "GET", "url": "http://x/"}

    scheduler._record_forward_result(endpoint_cfg, "skipped: moved less than 50m", None, "Test", now_ts=1)
    assert "consecutive_failures" not in endpoint_cfg  # skips don't start (or break) a failure streak

    scheduler._record_forward_result(endpoint_cfg, "error: boom", None, "Test", now_ts=2)
    assert endpoint_cfg["consecutive_failures"] == 1

    scheduler._record_forward_result(endpoint_cfg, "skipped: not updated in the last 30m", None, "Test", now_ts=3)
    assert endpoint_cfg["consecutive_failures"] == 1  # unchanged by the skip in between

    scheduler._record_forward_result(endpoint_cfg, "error: boom again", None, "Test", now_ts=4)
    assert endpoint_cfg["consecutive_failures"] == 2


def test_record_forward_result_escalates_at_the_threshold(caplog):
    endpoint_cfg = {"method": "GET", "url": "http://x/", "alias": "My server"}

    with caplog.at_level("ERROR", logger="webui.scheduler"):
        for _ in range(scheduler.FORWARD_FAILURE_ESCALATION_THRESHOLD - 1):
            scheduler._record_forward_result(endpoint_cfg, "error: boom", None, "Test")
        assert not caplog.records  # not yet at the threshold

        scheduler._record_forward_result(endpoint_cfg, "error: boom", None, "Test")
        assert len(caplog.records) == 1
        assert "My server" in caplog.records[0].message
        assert "Test" in caplog.records[0].message

        # keeps failing past the threshold -> escalates again at the next multiple, not every time
        for _ in range(scheduler.FORWARD_FAILURE_ESCALATION_THRESHOLD - 1):
            scheduler._record_forward_result(endpoint_cfg, "error: boom", None, "Test")
        assert len(caplog.records) == 1

        scheduler._record_forward_result(endpoint_cfg, "error: boom", None, "Test")
        assert len(caplog.records) == 2


def test_too_close_to_bother_requires_the_toggle_and_a_prior_position():
    location = {"is_semantic": False, "latitude": 45.0, "longitude": 9.0}

    # toggle off -> never skip, regardless of distance
    assert scheduler._too_close_to_bother(
        {"skip_if_close": False, "last_sent_lat": 45.0, "last_sent_lon": 9.0}, location,
    ) is False

    # toggle on but nothing sent yet -> never skip the first fix
    assert scheduler._too_close_to_bother({"skip_if_close": True}, location) is False

    # toggle on, within the default threshold of the last sent position -> skip
    assert scheduler._too_close_to_bother(
        {"skip_if_close": True, "last_sent_lat": 45.0, "last_sent_lon": 9.0}, location,
    ) is True

    # toggle on, well outside the threshold -> don't skip
    far_location = {"is_semantic": False, "latitude": 46.0, "longitude": 9.0}
    assert scheduler._too_close_to_bother(
        {"skip_if_close": True, "last_sent_lat": 45.0, "last_sent_lon": 9.0}, far_location,
    ) is False

    # semantic locations carry no coordinates - this check never applies to them
    assert scheduler._too_close_to_bother(
        {"skip_if_close": True, "last_sent_lat": 45.0, "last_sent_lon": 9.0},
        {"is_semantic": True, "latitude": None},
    ) is False


def test_stale_duplicate_requires_the_toggle_and_a_prior_send():
    now = 1_000_000.0
    stale_time = now - scheduler.FRESH_FIX_AGE_S - 1  # just past the "live" cutoff
    stale_location = {"is_semantic": False, "time": stale_time}

    # toggle off -> never skip, regardless of staleness
    assert scheduler._stale_duplicate(
        {"skip_if_stale": False, "last_sent_fix_time": stale_time}, stale_location, now=now,
    ) is False

    # toggle on but nothing sent yet -> never skip the first fix
    assert scheduler._stale_duplicate({"skip_if_stale": True}, stale_location, now=now) is False

    # toggle on, same stale fix time as last sent (within the default gap) -> skip
    assert scheduler._stale_duplicate(
        {"skip_if_stale": True, "last_sent_fix_time": stale_time}, stale_location, now=now,
    ) is True

    # toggle on, well outside the update gap -> don't skip
    older_last_sent = stale_time - (scheduler.DEFAULT_MIN_UPDATE_GAP_M * 60) - 1
    assert scheduler._stale_duplicate(
        {"skip_if_stale": True, "last_sent_fix_time": older_last_sent}, stale_location, now=now,
    ) is False

    # a genuinely live/fresh fix always bypasses the gate
    fresh_location = {"is_semantic": False, "time": now - 1}
    assert scheduler._stale_duplicate(
        {"skip_if_stale": True, "last_sent_fix_time": stale_time}, fresh_location, now=now,
    ) is False

    # semantic locations carry no fix time - this check never applies to them
    assert scheduler._stale_duplicate(
        {"skip_if_stale": True, "last_sent_fix_time": stale_time},
        {"is_semantic": True, "time": None}, now=now,
    ) is False


def test_forward_one_reports_stale_duplicate_skip_without_dispatching(monkeypatch):
    dispatched = []
    monkeypatch.setattr(scheduler, "_dispatch_forward", lambda cfg, loc, name="": dispatched.append(loc) or "ok")

    now = 1_000_000.0
    stale_time = now - scheduler.FRESH_FIX_AGE_S - 1
    endpoint_cfg = _traccar_endpoint(skip_if_stale=True, min_update_gap_m=10, last_sent_fix_time=stale_time)

    duplicate_location = {"is_semantic": False, "time": stale_time, "latitude": 1.0, "longitude": 2.0}
    monkeypatch.setattr(scheduler.time, "time", lambda: now)
    assert scheduler._forward_one(endpoint_cfg, duplicate_location) == "skipped: not updated in the last 10m"
    assert dispatched == []  # the network dispatch was never reached

    fresh_location = {"is_semantic": False, "time": now - 1, "latitude": 1.0, "longitude": 2.0}
    assert scheduler._forward_one(endpoint_cfg, fresh_location) == "ok"


def test_forward_one_reports_distance_skip_without_dispatching(monkeypatch):
    dispatched = []
    monkeypatch.setattr(scheduler, "_dispatch_forward", lambda cfg, loc, name="": dispatched.append(loc) or "ok")

    endpoint_cfg = _traccar_endpoint(skip_if_close=True, min_movement_m=100, last_sent_lat=45.0, last_sent_lon=9.0)

    close_location = {"is_semantic": False, "latitude": 45.0, "longitude": 9.0}
    assert scheduler._forward_one(endpoint_cfg, close_location) == "skipped: moved less than 100m"
    assert dispatched == []  # the network dispatch was never reached

    far_location = {"is_semantic": False, "latitude": 46.0, "longitude": 9.0}
    assert scheduler._forward_one(endpoint_cfg, far_location) == "ok"
    assert dispatched == [far_location]


async def test_poll_device_shares_one_locate_call_across_due_endpoints(monkeypatch, tmp_path):
    from webui import config
    from webui.forwarders import config_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "FORWARDING_CONFIG_PATH", tmp_path / "forwarding_config.json")
    monkeypatch.setattr(config, "FORWARD_LOG_PATH", tmp_path / "forward_log.json")

    monkeypatch.setattr(scheduler, "is_logged_in", lambda: True)

    call_count = {"n": 0}

    async def fake_locate_device(canonic_id, name):
        call_count["n"] += 1
        return [{"is_semantic": False, "latitude": 1.0, "longitude": 2.0, "time": 1}]

    monkeypatch.setattr(scheduler, "locate_device", fake_locate_device)

    canonic_id = "shared-tick-device"
    config_store.set_device_config(canonic_id, {
        "display_name": "Test",
        "endpoints": [
            _traccar_endpoint(cron="* * * * *", url="http://127.0.0.1:9/"),
            _traccar_endpoint(cron="* * * * *", url="http://127.0.0.1:9/", type="phonetrack"),
        ],
    })

    first_tick_done = asyncio.Event()
    orig_locate = fake_locate_device

    async def locate_then_signal(canonic_id, name):
        result = await orig_locate(canonic_id, name)
        first_tick_done.set()
        return result

    monkeypatch.setattr(scheduler, "locate_device", locate_then_signal)

    orig_sleep = asyncio.sleep

    async def fast_sleep(_secs):
        await orig_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", fast_sleep)

    task = asyncio.create_task(scheduler._poll_device(canonic_id))
    try:
        await asyncio.wait_for(first_tick_done.wait(), timeout=5)
    finally:
        monkeypatch.setattr(asyncio, "sleep", orig_sleep)
    await orig_sleep(0.5)  # let the forward+writeback following that locate call finish
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert call_count["n"] == 1

    cfg = config_store.get_device_config(canonic_id)
    for ep in cfg["endpoints"]:
        assert ep["last_forward_status"] is not None
        assert ep["last_forward_time"] is not None


async def test_poll_device_records_last_sent_position_on_success(monkeypatch, tmp_path):
    from webui import config
    from webui.forwarders import config_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "FORWARDING_CONFIG_PATH", tmp_path / "forwarding_config.json")
    monkeypatch.setattr(config, "FORWARD_LOG_PATH", tmp_path / "forward_log.json")
    monkeypatch.setattr(scheduler, "is_logged_in", lambda: True)
    monkeypatch.setattr(scheduler, "_dispatch_forward", lambda cfg, loc, name="": "ok")

    tick_done = asyncio.Event()

    async def locate_then_signal(canonic_id, name):
        tick_done.set()
        return [{"is_semantic": False, "latitude": 12.5, "longitude": 34.5, "time": 1}]

    monkeypatch.setattr(scheduler, "locate_device", locate_then_signal)

    orig_sleep = asyncio.sleep

    async def fast_sleep(_secs):
        await orig_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", fast_sleep)

    canonic_id = "position-tracking-device"
    config_store.set_device_config(canonic_id, {
        "display_name": "Test",
        "endpoints": [_traccar_endpoint(cron="* * * * *")],
    })

    task = asyncio.create_task(scheduler._poll_device(canonic_id))
    try:
        await asyncio.wait_for(tick_done.wait(), timeout=5)
    finally:
        monkeypatch.setattr(asyncio, "sleep", orig_sleep)
    await orig_sleep(0.5)  # let the forward+writeback following that locate call finish
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    ep = config_store.get_device_config(canonic_id)["endpoints"][0]
    assert ep["last_forward_status"] == "ok"
    assert ep["last_sent_lat"] == 12.5
    assert ep["last_sent_lon"] == 34.5


async def test_poll_device_persists_last_location_for_the_devices_page(monkeypatch, tmp_path):
    """A cron tick must update the Devices page's persisted "last locate
    result" the same as a manual click does - not just the per-endpoint
    forwarding bookkeeping above."""
    from webui import config, device_location_store
    from webui.forwarders import config_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "FORWARDING_CONFIG_PATH", tmp_path / "forwarding.yaml")
    monkeypatch.setattr(config, "FORWARD_LOG_PATH", tmp_path / "forward.log")
    monkeypatch.setattr(config, "DEVICE_LOCATIONS_PATH", tmp_path / "device_locations.yaml")
    monkeypatch.setattr(scheduler, "is_logged_in", lambda: True)
    monkeypatch.setattr(scheduler, "_dispatch_forward", lambda cfg, loc, name="": "ok")

    tick_done = asyncio.Event()
    fix = {"is_semantic": False, "latitude": 12.5, "longitude": 34.5, "time": 1}

    async def locate_then_signal(canonic_id, name):
        tick_done.set()
        return [fix]

    monkeypatch.setattr(scheduler, "locate_device", locate_then_signal)

    orig_sleep = asyncio.sleep

    async def fast_sleep(_secs):
        await orig_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", fast_sleep)

    canonic_id = "position-tracking-device-2"
    config_store.set_device_config(canonic_id, {
        "display_name": "Test",
        "endpoints": [_traccar_endpoint(cron="* * * * *")],
    })

    task = asyncio.create_task(scheduler._poll_device(canonic_id))
    try:
        await asyncio.wait_for(tick_done.wait(), timeout=5)
    finally:
        monkeypatch.setattr(asyncio, "sleep", orig_sleep)
    await orig_sleep(0.5)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    saved = device_location_store.get_last_location(canonic_id)
    assert saved is not None
    assert saved["locations"] == [fix]
