"""Unit tests for webui/device_list_cache.py's DeviceListCache - the shared
TTL cache webui/routers/devices.py and webui/routers/settings.py wrap their
slow Nova device-list fetch in. See tests/test_devices.py/test_settings.py
for the router-level "does a page load actually skip the second fetch"
coverage; these tests exercise the cache in isolation."""

import threading
import time

from webui.device_list_cache import DeviceListCache


class FakeClock:
    """Advances only when the test moves it forward - no real wall time
    passes, so TTL-expiry tests are deterministic and instant."""

    def __init__(self):
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now


def test_second_call_within_ttl_reuses_the_cached_value_without_refetching():
    clock = FakeClock()
    cache = DeviceListCache(ttl_s=10, clock=clock.monotonic)
    calls = []

    def fetch():
        calls.append(1)
        return "value"

    assert cache.get_or_fetch(fetch) == "value"
    clock.now = 5.0  # still within the 10s TTL
    assert cache.get_or_fetch(fetch) == "value"
    assert len(calls) == 1


def test_call_after_ttl_expiry_refetches():
    clock = FakeClock()
    cache = DeviceListCache(ttl_s=10, clock=clock.monotonic)
    calls = []

    def fetch():
        calls.append(1)
        return f"value-{len(calls)}"

    assert cache.get_or_fetch(fetch) == "value-1"
    clock.now = 10.0  # exactly at the TTL boundary - no longer "within" it
    assert cache.get_or_fetch(fetch) == "value-2"
    assert len(calls) == 2


def test_invalidate_forces_a_refetch_even_within_ttl():
    clock = FakeClock()
    cache = DeviceListCache(ttl_s=10, clock=clock.monotonic)
    calls = []

    def fetch():
        calls.append(1)
        return f"value-{len(calls)}"

    assert cache.get_or_fetch(fetch) == "value-1"
    cache.invalidate()
    assert cache.get_or_fetch(fetch) == "value-2"
    assert len(calls) == 2


def test_concurrent_misses_collapse_into_one_fetch():
    """Regression coverage for the single-flight guarantee: a burst of
    concurrent callers hitting a cold cache (e.g. /devices and /settings
    loading around the same time) must produce exactly one real fetch, not
    one per caller - see DeviceListCache.get_or_fetch's docstring for why
    the lock is deliberately held across the whole fetch here, unlike
    NovaApi/query_throttle.py's wait_turn()."""
    cache = DeviceListCache(ttl_s=10)  # real clock; the sleep below is real too
    calls = []
    call_lock = threading.Lock()

    def fetch():
        with call_lock:
            calls.append(1)
        time.sleep(0.1)
        return "value"

    results = []
    results_lock = threading.Lock()

    def worker():
        value = cache.get_or_fetch(fetch)
        with results_lock:
            results.append(value)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)
        assert not t.is_alive()

    assert len(calls) == 1
    assert results == ["value"] * 8
