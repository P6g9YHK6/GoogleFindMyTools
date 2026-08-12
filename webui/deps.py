import asyncio

from NovaApi.ExecuteAction.LocateTracker.location_request import get_location_data_for_device
from NovaApi.ExecuteAction.PlaySound.sound_action import play_sound
from NovaApi.query_throttle import query_throttle
from SpotApi.CreateBleDevice.create_ble_device import register_esp32
from webui import config, settings_store

_locate_semaphore = asyncio.Semaphore(config.LOCATE_CONCURRENCY)

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
    return await asyncio.to_thread(func, *args, **kwargs)


async def locate_device(canonic_id: str, name: str, timeout: float = config.LOCATE_TIMEOUT_S):
    async with _locate_semaphore:
        return await run_blocking(get_location_data_for_device, canonic_id, name, timeout)


async def set_sound(canonic_id: str, should_start: bool):
    return await run_blocking(play_sound, canonic_id, should_start)


async def register_tracker():
    return await run_blocking(register_esp32)
