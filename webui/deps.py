import asyncio

from NovaApi.ExecuteAction.LocateTracker.location_request import get_location_data_for_device
from NovaApi.ExecuteAction.PlaySound.sound_action import play_sound
from SpotApi.CreateBleDevice.create_ble_device import register_esp32
from webui import config

_locate_semaphore = asyncio.Semaphore(config.LOCATE_CONCURRENCY)


async def run_blocking(func, *args, **kwargs):
    return await asyncio.to_thread(func, *args, **kwargs)


async def locate_device(canonic_id: str, name: str, timeout: float = config.LOCATE_TIMEOUT_S):
    async with _locate_semaphore:
        return await run_blocking(get_location_data_for_device, canonic_id, name, timeout)


async def set_sound(canonic_id: str, should_start: bool):
    return await run_blocking(play_sound, canonic_id, should_start)


async def register_tracker():
    return await run_blocking(register_esp32)
