"""Tests for webui/scheduler.py's own concern: the cron-driven poll loop and
"send now" orchestration. The forwarding policy it calls into (skip-gates,
dispatch, failure escalation) is covered separately in
tests/test_forwarders_policy.py."""

import asyncio
from datetime import datetime

from webui import scheduler
from webui.forwarders import policy


def test_next_run_computes_next_cron_occurrence():
    base = datetime(2026, 8, 6, 12, 0, 0)
    assert scheduler._next_run("*/5 * * * *", base) == datetime(2026, 8, 6, 12, 5, 0)
    assert scheduler._next_run("* * * * *", base) == datetime(2026, 8, 6, 12, 1, 0)


def test_next_run_returns_none_for_invalid_cron():
    assert scheduler._next_run("not-a-cron", datetime.now()) is None


def test_cron_preview_returns_the_requested_number_of_future_runs():
    base = datetime(2026, 8, 6, 12, 0, 0)
    preview = scheduler.cron_preview("*/5 * * * *", count=3, base=base)
    assert preview == {
        "valid": True,
        "runs_str": ["2026-08-06 12:05", "2026-08-06 12:10", "2026-08-06 12:15"],
    }


def test_cron_preview_reports_invalid_expressions_without_raising():
    assert scheduler.cron_preview("not-a-cron") == {"valid": False}
    assert scheduler.cron_preview("") == {"valid": False}
    assert scheduler.cron_preview("   ") == {"valid": False}


def test_cron_preview_default_count_is_three():
    preview = scheduler.cron_preview("*/5 * * * *", base=datetime(2026, 8, 6, 12, 0, 0))
    assert len(preview["runs_str"]) == 3


def _traccar_endpoint(**overrides) -> dict:
    endpoint = {
        "type": "traccar", "method": "GET", "url": "http://x/",
        "params": {"id": "{{device_id}}", "lat": "{{latitude}}", "lon": "{{longitude}}"},
        "headers": {}, "body_type": "none", "body": "",
        "variables": {"device_id": "d1"},
    }
    endpoint.update(overrides)
    return endpoint


async def test_poll_device_shares_one_locate_call_across_due_endpoints(monkeypatch, tmp_path):
    from webui import config
    from webui.forwarders import config_store, latest_values_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "FORWARDING_CONFIG_PATH", tmp_path / "forwarding_config.json")
    monkeypatch.setattr(config, "FORWARD_LOG_PATH", tmp_path / "forward_log.json")
    monkeypatch.setattr(config, "LATEST_VALUES_PATH", tmp_path / "latest_values.yaml")

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

    # Both endpoints share this URL (after config_store's own one-time fold
    # of the legacy "params" dict into the URL's querystring - see
    # config_store._fold_params_into_url - so it's not literally the
    # "http://127.0.0.1:9/" passed to _traccar_endpoint above) - and so,
    # deliberately, the same recorded state too (see latest_values_store's
    # URL-keying) - just the one entry to check.
    url = config_store.get_device_config(canonic_id)["endpoints"][0]["url"]
    state = latest_values_store.get_endpoint_state(canonic_id, url)
    assert state["last_forward_status"] is not None
    assert state["last_forward_time"] is not None


async def test_poll_device_records_last_sent_position_on_success(monkeypatch, tmp_path):
    from webui import config
    from webui.forwarders import config_store, latest_values_store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "FORWARDING_CONFIG_PATH", tmp_path / "forwarding_config.json")
    monkeypatch.setattr(config, "FORWARD_LOG_PATH", tmp_path / "forward_log.json")
    monkeypatch.setattr(config, "LATEST_VALUES_PATH", tmp_path / "latest_values.yaml")
    monkeypatch.setattr(scheduler, "is_logged_in", lambda: True)
    # _poll_device calls policy._forward_one, which resolves _dispatch_forward
    # in policy's own module globals - patching scheduler's re-exported name
    # wouldn't reach it (see tests/conftest.py's "patch where it's looked up").
    monkeypatch.setattr(policy, "_dispatch_forward", lambda cfg, loc, name="", alias=None: "ok")

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
    assert "last_forward_status" not in ep  # not config anymore - see latest_values_store

    state = latest_values_store.get_endpoint_state(canonic_id, ep["url"])
    assert state["last_forward_status"] == "ok"
    assert state["last_sent_lat"] == 12.5
    assert state["last_sent_lon"] == 34.5


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
    monkeypatch.setattr(config, "LATEST_VALUES_PATH", tmp_path / "latest_values.yaml")
    monkeypatch.setattr(scheduler, "is_logged_in", lambda: True)
    monkeypatch.setattr(policy, "_dispatch_forward", lambda cfg, loc, name="", alias=None: "ok")

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
