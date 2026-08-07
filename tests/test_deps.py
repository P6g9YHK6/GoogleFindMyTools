import asyncio

import pytest

from webui import config
from webui.deps import QueryGate, run_blocking


class FakeClock:
    """A clock/sleep pair for QueryGate that advances instantly and in
    lockstep - real wall time never passes, so these tests are both
    deterministic and fast. Fine for tests that only care about the final
    elapsed time after a strictly sequential run of wait_turn() calls."""

    def __init__(self):
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float):
        self.now += seconds


class ManualClock:
    """Like FakeClock, but `sleep` blocks on a real asyncio.Event until the
    test explicitly releases it - lets a test observe QueryGate mid-wait
    deterministically, instead of guessing how many event-loop ticks an
    instant fake sleep needs to "complete" by."""

    def __init__(self):
        self.now = 0.0
        self.entered_sleep = asyncio.Event()
        self._release = asyncio.Event()

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float):
        self.now += seconds
        self.entered_sleep.set()
        await self._release.wait()


@pytest.fixture
def default_throttle(monkeypatch):
    monkeypatch.setattr(config, "QUERY_THROTTLE_MAX", 20)
    monkeypatch.setattr(config, "QUERY_THROTTLE_WINDOW_S", 60.0)
    monkeypatch.setattr(config, "QUERY_MIN_SPREAD_S", 1.0)


async def test_min_spread_delays_a_request_sent_too_soon(default_throttle, monkeypatch):
    monkeypatch.setattr(config, "QUERY_THROTTLE_MAX", 0)  # isolate the min-spread behavior
    clock = FakeClock()
    gate = QueryGate(clock=clock.monotonic, sleep=clock.sleep)

    await gate.wait_turn()
    assert clock.now == 0.0

    clock.now = 0.2  # only 0.2s later, under the 1s minimum spread
    await gate.wait_turn()
    assert clock.now == pytest.approx(1.0)  # waited out the remaining spread


async def test_throttle_waits_for_the_window_to_clear(default_throttle, monkeypatch):
    monkeypatch.setattr(config, "QUERY_MIN_SPREAD_S", 0)  # isolate the throttle behavior
    monkeypatch.setattr(config, "QUERY_THROTTLE_MAX", 2)
    monkeypatch.setattr(config, "QUERY_THROTTLE_WINDOW_S", 10.0)
    clock = FakeClock()
    gate = QueryGate(clock=clock.monotonic, sleep=clock.sleep)

    await gate.wait_turn()  # 1st in the window, at t=0
    await gate.wait_turn()  # 2nd in the window, at t=0
    assert clock.now == 0.0

    await gate.wait_turn()  # 3rd -> over the limit, must wait for the 1st to age out
    assert clock.now == pytest.approx(10.0)


async def test_zero_disables_a_limit(default_throttle, monkeypatch):
    monkeypatch.setattr(config, "QUERY_THROTTLE_MAX", 0)
    monkeypatch.setattr(config, "QUERY_MIN_SPREAD_S", 0)
    clock = FakeClock()
    gate = QueryGate(clock=clock.monotonic, sleep=clock.sleep)

    for _ in range(50):
        await gate.wait_turn()
    assert clock.now == 0.0  # never had to wait at all


async def test_waiting_counter_reflects_a_queued_request(default_throttle, monkeypatch):
    monkeypatch.setattr(config, "QUERY_THROTTLE_MAX", 1)
    monkeypatch.setattr(config, "QUERY_THROTTLE_WINDOW_S", 10.0)
    monkeypatch.setattr(config, "QUERY_MIN_SPREAD_S", 0)
    clock = ManualClock()
    gate = QueryGate(clock=clock.monotonic, sleep=clock.sleep)

    await gate.wait_turn()  # fills the window's only slot, at t=0
    assert gate.waiting == 0

    second = asyncio.create_task(gate.wait_turn())
    await asyncio.wait_for(clock.entered_sleep.wait(), timeout=1)
    assert gate.waiting == 1  # queued, mid-wait for the window to clear

    clock._release.set()
    await asyncio.wait_for(second, timeout=1)
    assert gate.waiting == 0


async def test_run_blocking_still_calls_the_wrapped_function(monkeypatch):
    monkeypatch.setattr(config, "QUERY_THROTTLE_MAX", 0)
    monkeypatch.setattr(config, "QUERY_MIN_SPREAD_S", 0)

    result = await run_blocking(lambda x, y: x + y, 2, y=3)
    assert result == 5
