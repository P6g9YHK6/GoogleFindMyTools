import asyncio
import threading
import time

from webui.deps import run_blocking


async def test_run_blocking_calls_the_wrapped_function():
    result = await run_blocking(lambda x, y: x + y, 2, y=3)
    assert result == 5


async def test_concurrent_locate_device_calls_for_the_same_device_share_one_fetch(monkeypatch):
    """Regression coverage for webui/locate_coalescer.py: a poll tick and a
    manual click landing on the same device at the same moment must produce
    exactly one Nova+FCM round trip, not one per caller - see
    webui.deps.locate_device's own comment."""
    import webui.deps as deps

    calls = []
    # threading.Event, not asyncio.Event: fake_get_location_data_for_device
    # runs on deps._executor's worker thread (via run_blocking), and
    # asyncio.Event isn't safe to .set() from a thread other than the
    # event loop's.
    started = threading.Event()

    def fake_get_location_data_for_device(canonic_id, name, timeout):
        calls.append(canonic_id)
        started.set()
        time.sleep(0.05)
        return ["a location"]

    monkeypatch.setattr(deps, "get_location_data_for_device", fake_get_location_data_for_device)

    async def caller():
        return await deps.locate_device("dev-1", "Device One")

    t1 = asyncio.ensure_future(caller())
    while not started.is_set():
        await asyncio.sleep(0.005)
    t2 = asyncio.ensure_future(caller())

    results = await asyncio.gather(t1, t2)

    assert results == [["a location"], ["a location"]]
    assert calls == ["dev-1"]


def test_webui_points_the_shared_throttle_at_settings_store():
    """webui/deps.py reconfigures NovaApi/query_throttle.py's shared
    singleton to read config.yaml (via settings_store.load, editable on the
    Config page) instead of the env-var defaults that apply when running
    standalone via the CLI - see NovaApi/query_throttle.py's module
    docstring."""
    from NovaApi.query_throttle import query_throttle as shared_throttle
    from webui import settings_store
    from webui.deps import query_gate

    assert query_gate is shared_throttle
    assert query_gate._settings is settings_store.load
