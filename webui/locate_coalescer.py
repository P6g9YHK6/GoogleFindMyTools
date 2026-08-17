"""Single-flight coalescing for concurrent locate requests aimed at the same
device. webui/deps.py's locate_device() is the one seam every locate call
goes through - the manual "Locate" button (webui/routers/locate.py), the
background cron poller (webui/scheduler.py's _poll_device, which already
merges across one device's own endpoints into a single call per wake tick -
see its own docstring), and a per-endpoint "send now" (webui/scheduler.py's
forward_now). Those three can still land within moments of each other for
the *same* device - e.g. a poll tick fires just as someone clicks Locate -
each of which would otherwise cost its own Nova HTTP POST + FCM round trip
and its own query_throttle slot for what is, semantically, one request.

Unlike webui/device_list_cache.py (a single keyless slot with a TTL - this
app only ever has one Google account, so the whole cache can be shared),
every device needs its own slot here, and there's no TTL: a locate result is
only ever worth sharing with callers that asked for it *before* it existed,
never with the next caller to come along afterward.

asyncio, not threading: every caller reaches this from a coroutine running
on the single event-loop thread (see webui/serve.py - no `workers=` passed
to uvicorn.run(), so there is exactly one), not from worker threads, unlike
DeviceListCache.get_or_fetch (which is reached via webui/deps.py's
run_blocking). Coalescing happens here, above run_blocking and the locate
semaphore, so a caller that joins an in-flight locate never occupies a
semaphore slot or executor thread of its own - it just awaits the same
result.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")


class LocateCoalescer:
    def __init__(self):
        self._inflight: dict[str, asyncio.Task] = {}

    async def get_or_fetch(self, key: str, fetch: Callable[[], Awaitable[T]]) -> T:
        """Runs fetch() for `key` unless one's already in flight, in which
        case this call joins it instead of starting its own. Every caller -
        leader and joiners alike - gets back the exact same result (or the
        exact same exception, re-raised) once it's ready."""
        task = self._inflight.get(key)
        if task is None:
            task = asyncio.ensure_future(fetch())
            self._inflight[key] = task

            def _clear(finished: asyncio.Task, key=key) -> None:
                # Only clear the slot if it's still pointing at this task -
                # a rare stale-callback vs. a new in-flight task for the
                # same key must never delete the wrong one.
                if self._inflight.get(key) is finished:
                    del self._inflight[key]

            task.add_done_callback(_clear)
        # shield() so a joining caller being cancelled (e.g. its own request
        # got dropped) never cancels the fetch other callers are still
        # waiting on - only the shield itself is cancelled, the underlying
        # task runs to completion regardless.
        return await asyncio.shield(task)


locate_coalescer = LocateCoalescer()
