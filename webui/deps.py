import asyncio
import time
from collections import deque
from collections.abc import Callable

from Auth.live_device_info import open_watch as _open_live_info_watch
from NovaApi.ExecuteAction.LocateTracker.location_request import get_location_data_for_device
from NovaApi.ExecuteAction.PlaySound.sound_action import play_sound
from SpotApi.CreateBleDevice.create_ble_device import register_esp32
from webui import config, settings_store

_locate_semaphore = asyncio.Semaphore(config.LOCATE_CONCURRENCY)


class QueryGate:
    """Serializes every blocking call to Google's backend through one rate
    limiter, so a burst of manual clicks plus every device's poll loop can
    never hammer Google faster than the account-wide throttle allows: at
    most query_throttle_max requests within any rolling
    query_throttle_window_s-second window, and at least query_min_spread_s
    seconds between any two consecutive requests. These come from
    webui/settings_store.py (config.yaml, editable on the Config page),
    which falls back to the env-var defaults in webui/config.py when unset.
    Over either limit, callers wait their turn instead of failing -
    `waiting` is how many are queued right now, for the Config page's live
    counter.

    clock/sleep/settings are injected (defaulting to real time and the real
    store) so tests can run this against a fake, instantly-advancing clock
    instead of real wall time.
    """

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        sleep=asyncio.sleep,
        settings: Callable[[], dict] = settings_store.load,
    ):
        self._clock = clock
        self._sleep = sleep
        self._settings = settings
        self._lock = asyncio.Lock()
        self._sent_at: deque[float] = deque()
        self._last_sent_at: float | None = None
        self.waiting = 0

    async def wait_turn(self):
        self.waiting += 1
        try:
            async with self._lock:
                while True:
                    now = self._clock()
                    settings = self._settings()
                    window = settings["query_throttle_window_s"]
                    max_per_window = settings["query_throttle_max"]
                    min_spread = settings["query_min_spread_s"]

                    while self._sent_at and now - self._sent_at[0] >= window:
                        self._sent_at.popleft()

                    delay = 0.0
                    if max_per_window > 0 and len(self._sent_at) >= max_per_window:
                        delay = max(delay, window - (now - self._sent_at[0]))
                    if min_spread > 0 and self._last_sent_at is not None:
                        delay = max(delay, min_spread - (now - self._last_sent_at))

                    if delay <= 0:
                        break
                    await self._sleep(delay)

                now = self._clock()
                self._sent_at.append(now)
                self._last_sent_at = now
        finally:
            self.waiting -= 1


query_gate = QueryGate()


async def run_blocking(func, *args, **kwargs):
    # Every current caller of run_blocking (device list, locate, sound,
    # register - grep the callers) is a real query to Google's backend, which
    # makes this the one place to gate all of them at once.
    await query_gate.wait_turn()
    return await asyncio.to_thread(func, *args, **kwargs)


async def locate_device(canonic_id: str, name: str, timeout: float = config.LOCATE_TIMEOUT_S):
    async with _locate_semaphore:
        return await run_blocking(get_location_data_for_device, canonic_id, name, timeout)


async def set_sound(canonic_id: str, should_start: bool):
    return await run_blocking(play_sound, canonic_id, should_start)


async def register_tracker():
    return await run_blocking(register_esp32)


async def open_live_info_watch(canonic_id: str):
    """See Auth/live_device_info.py's module docstring - must be called
    before the matching locate_device(), not after. Goes through the same
    QueryGate throttle as every other Google call; returns None on any
    failure (including the feature simply being off), never raises."""
    return await run_blocking(_open_live_info_watch, canonic_id)
