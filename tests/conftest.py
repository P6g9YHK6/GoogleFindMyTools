"""Shared test fixtures.

Every webui/routers/* module does non-lazy, top-level `from X import Y`
imports, and webui/main.py imports every router unconditionally - so merely
importing webui.main drags in the entire heavy dependency chain (selenium,
undetected-chromedriver, gpsoauth, aiohttp, ...). CI installs all of
requirements.txt + requirements-web.txt for real (proven safe: the project's
own Dockerfile already does exactly that, with no browser/Xvfb present, since
those are only installed at runtime on first login - see
webui/browser_provisioning.py) rather than hand-stubbing those packages.

Real Google/network calls are avoided instead at the function boundary, via
monkeypatch - and because each router does `from webui.deps import X` rather
than `from webui import deps`, patches must target each router MODULE's own
bound name ("patch where it's looked up"), not webui.deps/webui.auth_state
directly.
"""

import os
import tempfile

# Must happen before anything under webui/Auth is first imported - DATA_DIR/
# secrets paths are computed once, at import time, from these env vars.
os.environ["GFMT_DATA_DIR"] = tempfile.mkdtemp(prefix="gfmt-test-data-")
os.environ["GFMT_SECRETS_DIR"] = tempfile.mkdtemp(prefix="gfmt-test-secrets-")
os.environ["GFMT_NONINTERACTIVE"] = "1"
# NovaApi/query_throttle.py's shared singleton is a real module-level global,
# not reset between tests - without this, two nova_request()/spot_request()
# calls anywhere in the suite (even in unrelated test files) less than 1s of
# real wall-clock time apart would trigger a real time.sleep() via its
# min-spread check. Tests that actually want throttle behavior construct
# their own QueryThrottle(settings=...) instance directly instead of relying
# on these env-var defaults - see tests/test_query_throttle.py.
os.environ.setdefault("QUERY_THROTTLE_MAX", "0")
os.environ.setdefault("QUERY_MIN_SPREAD_S", "0")
os.environ.pop("HTTP_USER", None)  # deterministic: no basic auth in tests
os.environ.pop("HTTP_PASSWORD", None)
os.environ.pop("HTTPS_ENABLED", None)  # deterministic: no self-signed TLS in tests
os.environ.pop("GFMT_TLS_CERT_PATH", None)
os.environ.pop("GFMT_TLS_KEY_PATH", None)
os.environ.pop("GFMT_TLS_SAN", None)
os.environ.pop("APPRISE_URLS", None)  # deterministic: no real notifications fired from tests

import pytest  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

# A stand-in device list every "logged in" test sees by default.
FAKE_DEVICE_NAME = "My Tracker"
FAKE_CANONIC_ID = "test-canonic-id"
FAKE_LAST_SEEN = 1700000000  # phone-only field - see ProtoDecoders/decoder.py:get_last_seen


@pytest.fixture(autouse=True)
def stub_backend(monkeypatch):
    """Sane defaults for every router's external-service boundary, so most
    tests get a working "happy path" for free and only override what they
    specifically care about."""
    from webui.device_list_cache import device_list_cache
    from webui.routers import auth, devices, locate, logs, register, settings, sound

    # webui/device_list_cache.py's singleton is a real module-level global
    # like query_throttle above - without this, a value cached by one test
    # (well within its default 8s TTL; tests run in milliseconds) would
    # leak into the next test instead of that test's own monkeypatched
    # get_canonic_ids/request_device_list ever actually running.
    device_list_cache.invalidate()

    def fake_get_canonic_ids(device_list):
        return [(FAKE_DEVICE_NAME, FAKE_CANONIC_ID, FAKE_LAST_SEEN)]

    for mod in (devices, settings, logs):
        monkeypatch.setattr(mod, "is_logged_in", lambda: True)
    for mod in (devices, settings):
        monkeypatch.setattr(mod, "request_device_list", lambda: b"")
        monkeypatch.setattr(mod, "parse_device_list_protobuf", lambda hex: None)
        monkeypatch.setattr(mod, "get_canonic_ids", fake_get_canonic_ids)

    monkeypatch.setattr(devices, "refresh_custom_trackers", lambda device_list: None)
    monkeypatch.setattr(auth, "is_logged_in", lambda: True)

    async def fake_locate_device(canonic_id, name, timeout=None):
        return [{"is_semantic": False, "latitude": 1.0, "longitude": 2.0, "time": 1}]

    monkeypatch.setattr(locate, "locate_device", fake_locate_device)

    async def fake_set_sound(canonic_id, should_start):
        return {"ok": True}

    monkeypatch.setattr(sound, "set_sound", fake_set_sound)

    async def fake_register_tracker():
        return {"eid_hex": "deadbeef"}

    monkeypatch.setattr(register, "register_tracker", fake_register_tracker)


@pytest.fixture
def client():
    """Runs the real app, including its lifespan (scheduler.start_all() /
    browser_provisioning.on_shutdown()) - both are no-ops against the empty
    per-test data dir set up above, so this doubles as a smoke test that the
    app actually boots and shuts down cleanly."""
    from webui.main import app

    with TestClient(app) as c:
        yield c
