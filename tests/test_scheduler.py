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


def test_forward_one_dispatches_via_registry():
    location = {"is_semantic": False, "latitude": 1.0, "longitude": 2.0, "time": 1}

    # empty url -> httpx raises before any network call, dispatch still worked
    status = scheduler._forward_one({"type": "traccar", "traccar": {"url": "", "device_id": ""}}, location)
    assert status.startswith("error:")

    assert scheduler._forward_one({"type": "unregistered-type"}, location) == "skipped"


def test_endpoint_target_uses_registry_label():
    target = scheduler._endpoint_target({"type": "phonetrack", "phonetrack": {"base_url": "http://y", "device_name": "p1"}})
    assert target == "http://y (p1)"
    assert scheduler._endpoint_target({"type": "unregistered-type"}) == ""


def test_endpoint_target_is_prefixed_with_alias_when_set():
    target = scheduler._endpoint_target({
        "type": "phonetrack", "phonetrack": {"base_url": "http://y", "device_name": "p1"}, "alias": "My phone",
    })
    assert target == "My phone (http://y (p1))"


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


def test_forward_one_reports_distance_skip_without_dispatching(monkeypatch):
    dispatched = []
    monkeypatch.setattr(scheduler, "_dispatch_forward", lambda cfg, loc: dispatched.append(loc) or "ok")

    endpoint_cfg = {
        "type": "traccar", "traccar": {"url": "http://x", "device_id": "d1"},
        "skip_if_close": True, "min_movement_m": 100, "last_sent_lat": 45.0, "last_sent_lon": 9.0,
    }

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
            {"type": "traccar", "traccar": {"url": "http://127.0.0.1:9", "device_id": "d1"}, "cron": "* * * * *"},
            {"type": "phonetrack", "phonetrack": {"base_url": "http://127.0.0.1:9", "device_name": "d2"}, "cron": "* * * * *"},
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
    monkeypatch.setattr(scheduler, "_dispatch_forward", lambda cfg, loc: "ok")

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
        "endpoints": [{
            "type": "traccar", "traccar": {"url": "http://x", "device_id": "d1"}, "cron": "* * * * *",
        }],
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
