import asyncio
from concurrent.futures import ThreadPoolExecutor

from NovaApi.ExecuteAction.LocateTracker.location_request import get_location_data_for_device
from NovaApi.ExecuteAction.PlaySound.sound_action import play_sound
from NovaApi.query_throttle import query_throttle
from SpotApi.CreateBleDevice.create_ble_device import register_esp32
from webui import config, settings_store
from webui.device_list_cache import device_list_cache

_locate_semaphore = asyncio.Semaphore(config.LOCATE_CONCURRENCY)

# asyncio.to_thread() would use the process-wide default executor, sized
# min(32, cpu_count + 4) - on a small container that's often 5-8 workers,
# shared with anything else in the process that happens to use the default
# executor. Every blocking call this app makes (device list, locate, sound,
# register - one poll tick per device too, see webui/scheduler.py) goes
# through here, and each one can now legitimately sit waiting on
# query_throttle for a few seconds if several devices' polls land close
# together (the common case: anything on the default schedule shares the
# same */5 * * * * tick) - a small shared pool meant a handful of those
# waits alone could exhaust every worker, leaving unrelated requests (a
# page load, a manual click) with no thread to run on at all. A dedicated,
# generously-sized pool here means a throttle wait only ever costs its own
# slot, not the whole app's ability to serve anything else.
_executor = ThreadPoolExecutor(max_workers=32, thread_name_prefix="gfmt-blocking")

# The actual rate limiter lives in NovaApi/query_throttle.py now - it's the
# same instance NovaApi/nova_request.py and SpotApi/spot_request.py wait on
# directly, so every call to Google's backend is gated exactly once,
# whether it came from here or from the CLI. `query_gate` stays as a name
# so webui/routers/auth.py and webui/routers/metrics.py (which read
# `query_gate.waiting`) don't need to change. Point it at config.yaml
# (editable on the Config page) instead of the env-var defaults that apply
# when running standalone via the CLI.
query_gate = query_throttle
query_throttle.configure(settings=settings_store.load)


async def run_blocking(func, *args, **kwargs):
    # No explicit throttle wait here anymore - nova_request()/spot_request()
    # (the two actual HTTP call points, wherever func eventually reaches
    # them) already wait their turn on the same query_throttle instance.
    # Dispatched onto _executor rather than asyncio.to_thread()'s default
    # pool - see _executor's own comment above.
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, lambda: func(*args, **kwargs))


async def locate_device(canonic_id: str, name: str, timeout: float = config.LOCATE_TIMEOUT_S):
    async with _locate_semaphore:
        return await run_blocking(get_location_data_for_device, canonic_id, name, timeout)


async def set_sound(canonic_id: str, should_start: bool):
    return await run_blocking(play_sound, canonic_id, should_start)


async def register_tracker():
    result = await run_blocking(register_esp32)
    # register_esp32() raises on failure rather than returning a sentinel,
    # so getting here already means success - invalidate the device-list
    # cache (see webui/device_list_cache.py) so the newly-registered
    # tracker shows up on the very next /devices/table load instead of
    # waiting out its TTL.
    device_list_cache.invalidate()
    return result
