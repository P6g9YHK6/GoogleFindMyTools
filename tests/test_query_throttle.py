"""Unit tests for NovaApi/query_throttle.py's QueryThrottle - the same
account-wide rate limiter algorithm formerly in webui/deps.py's QueryGate,
now relocated so NovaApi/nova_request.py and SpotApi/spot_request.py (the
actual HTTP call points, used by both the CLI and the web UI) can wait on
it directly. See tests/test_deps.py for confirmation that webui points the
shared singleton at its own live-editable settings instead of these tests'
fixed ones."""

import threading

import pytest

from NovaApi.query_throttle import QueryThrottle


class FakeClock:
    """A clock/sleep pair that advances instantly and in lockstep - real
    wall time never passes, so these tests are both deterministic and
    fast. Fine for tests that only care about the final elapsed time after
    a strictly sequential run of wait_turn() calls."""

    def __init__(self):
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float):
        self.now += seconds


class ManualClock:
    """Like FakeClock, but `sleep` blocks on a real threading.Event until
    the test explicitly releases it - lets a test observe QueryThrottle
    mid-wait deterministically, instead of guessing how many ticks an
    instant fake sleep needs to "complete" by."""

    def __init__(self):
        self.now = 0.0
        self.entered_sleep = threading.Event()
        self._release = threading.Event()

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float):
        self.now += seconds
        self.entered_sleep.set()
        self._release.wait(timeout=1)


def _settings(max_per_window=20, window_s=60.0, min_spread_s=1.0):
    return lambda: {
        "query_throttle_max": max_per_window,
        "query_throttle_window_s": window_s,
        "query_min_spread_s": min_spread_s,
    }


def test_min_spread_delays_a_request_sent_too_soon():
    clock = FakeClock()
    throttle = QueryThrottle(clock=clock.monotonic, sleep=clock.sleep,
                              settings=_settings(max_per_window=0, min_spread_s=1.0))

    throttle.wait_turn()
    assert clock.now == 0.0

    clock.now = 0.2  # only 0.2s later, under the 1s minimum spread
    throttle.wait_turn()
    assert clock.now == pytest.approx(1.0)  # waited out the remaining spread


def test_throttle_waits_for_the_window_to_clear():
    clock = FakeClock()
    throttle = QueryThrottle(clock=clock.monotonic, sleep=clock.sleep,
                              settings=_settings(max_per_window=2, window_s=10.0, min_spread_s=0))

    throttle.wait_turn()  # 1st in the window, at t=0
    throttle.wait_turn()  # 2nd in the window, at t=0
    assert clock.now == 0.0

    throttle.wait_turn()  # 3rd -> over the limit, must wait for the 1st to age out
    assert clock.now == pytest.approx(10.0)


def test_zero_disables_a_limit():
    clock = FakeClock()
    throttle = QueryThrottle(clock=clock.monotonic, sleep=clock.sleep,
                              settings=_settings(max_per_window=0, min_spread_s=0))

    for _ in range(50):
        throttle.wait_turn()
    assert clock.now == 0.0  # never had to wait at all


def test_waiting_counter_reflects_a_queued_request():
    clock = ManualClock()
    throttle = QueryThrottle(clock=clock.monotonic, sleep=clock.sleep,
                              settings=_settings(max_per_window=1, window_s=10.0, min_spread_s=0))

    throttle.wait_turn()  # fills the window's only slot, at t=0
    assert throttle.waiting == 0

    thread = threading.Thread(target=throttle.wait_turn)
    thread.start()
    assert clock.entered_sleep.wait(timeout=1)
    assert throttle.waiting == 1  # queued, mid-wait for the window to clear

    clock._release.set()
    thread.join(timeout=1)
    assert throttle.waiting == 0


def test_configure_swaps_the_settings_source_on_the_same_instance():
    """webui/deps.py relies on this: it needs to redirect the *shared*
    singleton NovaApi/nova_request.py already imported to config.yaml,
    not replace it with a new object other modules wouldn't see."""
    throttle = QueryThrottle(sleep=lambda seconds: None)
    calls = []

    def fake_settings():
        calls.append(1)
        return {"query_throttle_max": 0, "query_throttle_window_s": 60, "query_min_spread_s": 0}

    throttle.configure(settings=fake_settings)
    throttle.wait_turn()
    assert calls == [1]


def test_nova_request_waits_on_the_shared_throttle(monkeypatch):
    import NovaApi.nova_request as nova_request_module

    calls = []
    monkeypatch.setattr(nova_request_module.query_throttle, "wait_turn", lambda: calls.append("nova"))
    monkeypatch.setattr(nova_request_module, "get_username", lambda: "user@example.com")
    monkeypatch.setattr(nova_request_module, "get_adm_token", lambda username: "fake-token")

    class FakeResponse:
        status_code = 200
        content = b"\xde\xad"

    monkeypatch.setattr(nova_request_module.requests, "post", lambda *a, **kw: FakeResponse())

    nova_request_module.nova_request("someScope", "00")
    assert calls == ["nova"]


def test_spot_request_waits_on_the_shared_throttle(monkeypatch):
    import SpotApi.spot_request as spot_request_module

    calls = []
    monkeypatch.setattr(spot_request_module.query_throttle, "wait_turn", lambda: calls.append("spot"))
    monkeypatch.setattr(spot_request_module, "get_spot_token", lambda username: "fake-token")
    monkeypatch.setattr(spot_request_module, "get_username", lambda: "user@example.com")
    monkeypatch.setattr(spot_request_module.GrpcParser, "construct_grpc", staticmethod(lambda payload: payload))
    monkeypatch.setattr(spot_request_module.GrpcParser, "extract_grpc_payload", staticmethod(lambda content: content))

    class FakeResponse:
        status_code = 200
        content = b"\xde\xad"
        text = ""

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def post(self, *a, **kw):
            return FakeResponse()

    monkeypatch.setattr(spot_request_module.httpx, "Client", lambda *a, **kw: FakeClient())

    spot_request_module.spot_request("SomeScope", b"payload")
    assert calls == ["spot"]


def test_nova_request_and_spot_request_share_one_throttle_instance():
    import NovaApi.nova_request as nova_request_module
    import SpotApi.spot_request as spot_request_module

    assert nova_request_module.query_throttle is spot_request_module.query_throttle
