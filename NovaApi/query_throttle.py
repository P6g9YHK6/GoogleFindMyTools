#
#  GoogleFindMyTools - A set of tools to interact with the Google Find My API
#  Copyright © 2024 Leon Böttger. All rights reserved.
#
"""Account-wide rate limiter for every blocking call this tool makes to
Google's Nova/Spot backend. Used directly by NovaApi/nova_request.py and
SpotApi/spot_request.py - the two actual HTTP call points, so gating there
covers every caller (CLI and web UI alike) without touching each call site
individually. webui/deps.py reconfigures the shared instance's settings
source to its own live-editable config.yaml instead of the env-var
defaults below, via configure().
"""

import os
import threading
import time
from collections import deque
from collections.abc import Callable


def _default_settings() -> dict:
    """Env-var defaults, used standalone by the CLI. webui overrides this
    via configure(settings=...) so the Config page's live-editable values
    apply there instead."""
    return {
        "query_throttle_max": int(os.environ.get("QUERY_THROTTLE_MAX", "20")),
        "query_throttle_window_s": float(os.environ.get("QUERY_THROTTLE_WINDOW_S", "60")),
        "query_min_spread_s": float(os.environ.get("QUERY_MIN_SPREAD_S", "1")),
    }


class QueryThrottle:
    """Serializes every blocking call to Google's backend through one rate
    limiter, so a burst of manual clicks plus every device's poll loop can
    never hammer Google faster than the account-wide throttle allows: at
    most query_throttle_max requests within any rolling
    query_throttle_window_s-second window, and at least query_min_spread_s
    seconds between any two consecutive requests. Over either limit,
    callers wait their turn instead of failing - `waiting` is how many are
    queued right now (surfaced on the web UI's Config page and /metrics).

    Synchronous and thread-safe (a plain threading.Lock, not asyncio.Lock)
    so the same instance works whether it's called from the CLI's single
    thread or from the web UI's asyncio.to_thread-dispatched worker
    threads - see webui/deps.py's run_blocking.

    clock/sleep/settings are injected (defaulting to real time and the
    env-var settings above) so tests can run this against a fake,
    instantly-advancing clock instead of real wall time, and so
    configure() can swap in a different settings source later without
    losing the object identity other modules already imported.
    """

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        settings: Callable[[], dict] = _default_settings,
    ):
        self._clock = clock
        self._sleep = sleep
        self._settings = settings
        self._lock = threading.Lock()
        self._sent_at: deque[float] = deque()
        self._last_sent_at: float | None = None
        self.waiting = 0

    def configure(
        self,
        *,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
        settings: Callable[[], dict] | None = None,
    ):
        """Overrides one or more of clock/sleep/settings on this same
        instance in place, so callers that already hold a reference to it
        (e.g. NovaApi/nova_request.py's module-level import) keep using
        the updated behavior without needing to know it changed."""
        if clock is not None:
            self._clock = clock
        if sleep is not None:
            self._sleep = sleep
        if settings is not None:
            self._settings = settings

    def wait_turn(self):
        self.waiting += 1
        try:
            with self._lock:
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
                    self._sleep(delay)

                now = self._clock()
                self._sent_at.append(now)
                self._last_sent_at = now
        finally:
            self.waiting -= 1


query_throttle = QueryThrottle()
