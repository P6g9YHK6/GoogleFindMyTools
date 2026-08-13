"""Very short-lived (single-digit-seconds) cache around the Nova
device-list call both webui/routers/devices.py and webui/routers/settings.py
hit on every page load (devices/list.html's #device-table has
hx-trigger="load", no auto-polling - so "every page load" really is the
whole story) - the slowest thing either page does. One shared, keyless,
process-wide slot: this app only ever talks to one signed-in Google account
at a time, so there's nothing to key by.

Deliberately NOT in NovaApi/ListDevices/nbe_list_devices.py itself - that
module's list_devices() is also the CLI entry point (a separate process
invocation every run) and must never see stale/cached data just because a
webui process happened to fetch recently.

Same shape as NovaApi/query_throttle.py: injectable clock, threading.Lock-
guarded bookkeeping, one module-level singleton. Callers supply their own
fetch closure rather than this module calling
NovaApi.ListDevices.nbe_list_devices.request_device_list() itself, so
existing tests' monkeypatch.setattr(devices, "request_device_list", ...)-
style patching (see tests/conftest.py - each router does `from
NovaApi.ListDevices.nbe_list_devices import request_device_list` as its own
bound name, patched there rather than at the source) keeps working
untouched.
"""

import threading
import time
from collections.abc import Callable
from typing import TypeVar

from webui import config

T = TypeVar("T")


class DeviceListCache:
    """Caches whatever a caller's `fetch` closure returns, for `ttl_s`
    seconds. get_or_fetch() is single-flight under concurrent misses: the
    lock is held across the whole fetch call, not just the bookkeeping -
    unlike NovaApi/query_throttle.py's wait_turn(), which deliberately does
    NOT hold its lock across a sleep. Here, holding it across the fetch is
    the point: a burst of concurrent callers past expiry (e.g. /devices and
    /settings loading around the same time) collapse into exactly one real
    Nova API call instead of a thundering herd, at the cost of one caller
    briefly blocking the others - an acceptable trade since the fetch itself
    is the slow thing everyone's waiting on anyway.

    threading.Lock, not asyncio.Lock: concurrent page loads/htmx requests
    reach this from real worker threads (see webui/deps.py's run_blocking,
    backed by a dedicated ThreadPoolExecutor), not just concurrent
    coroutines on one event loop thread.
    """

    def __init__(self, ttl_s: float = 8.0, clock: Callable[[], float] = time.monotonic):
        self._ttl_s = ttl_s
        self._clock = clock
        self._lock = threading.Lock()
        self._value: object = None
        self._fetched_at: float | None = None
        self._has_value = False

    def get_or_fetch(self, fetch: Callable[[], T]) -> T:
        with self._lock:
            now = self._clock()
            if self._has_value and self._fetched_at is not None and now - self._fetched_at < self._ttl_s:
                return self._value  # type: ignore[return-value]
            value = fetch()
            self._value = value
            self._fetched_at = self._clock()
            self._has_value = True
            return value

    def invalidate(self):
        """Forces the next get_or_fetch() to actually fetch, regardless of
        TTL - e.g. right after registering a new tracker (see
        webui/deps.py's register_tracker), so it shows up on the very next
        page load instead of waiting out the TTL."""
        with self._lock:
            self._has_value = False
            self._value = None
            self._fetched_at = None


device_list_cache = DeviceListCache(ttl_s=config.DEVICE_LIST_CACHE_TTL_S)
