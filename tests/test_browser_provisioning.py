import asyncio
import time
import urllib.request

import pytest

import webui.browser_provisioning as browser_provisioning
from webui import config


class _FakeProc:
    """Stands in for an asyncio.subprocess.Process for _kill_chrome's own
    pkill/pgrep calls (which it spawns internally), so this never shells out
    for real."""

    def __init__(self, returncode=0):
        self.returncode = returncode

    async def wait(self):
        return self.returncode


async def test_kill_chrome_confirms_clean_exit(monkeypatch):
    browser_provisioning._chrome_bin = "/fake/chrome"

    async def fake_exec(*args, **kwargs):
        if args[0] == "pkill":
            return _FakeProc(0)
        if args[0] == "pgrep":
            return _FakeProc(1)  # not found -> gone
        raise AssertionError(f"unexpected exec {args}")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    assert await browser_provisioning._kill_chrome() is None


async def test_kill_chrome_reports_stuck_process(monkeypatch):
    browser_provisioning._chrome_bin = "/fake/chrome"

    async def fake_exec(*args, **kwargs):
        if args[0] == "pkill":
            return _FakeProc(0)
        if args[0] == "pgrep":
            return _FakeProc(0)  # still found, every poll
        raise AssertionError(f"unexpected exec {args}")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    t0 = time.monotonic()
    result = await browser_provisioning._kill_chrome()
    dt = time.monotonic() - t0
    assert result == "Chrome"
    assert dt < 6  # bounded polling window, not an indefinite hang


async def test_teardown_reports_a_process_that_ignores_sigterm():
    browser_provisioning._chrome_bin = None  # isolate to the tracked-process path only
    browser_provisioning._processes.clear()

    proc = await asyncio.create_subprocess_exec(
        "python3", "-c", "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)",
    )
    try:
        await asyncio.sleep(0.3)  # let it install the signal handler before we terminate() it
        browser_provisioning._processes["stubborn"] = proc

        t0 = time.monotonic()
        await browser_provisioning._teardown("done", "ok")
        dt = time.monotonic() - t0

        assert dt < 6  # concurrent kill/wait, not stacked sequentially
        assert "stubborn" in browser_provisioning.get_state()["cleanup_warning"]
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()


async def test_teardown_reports_no_warning_when_everything_exits_cleanly():
    browser_provisioning._chrome_bin = None
    browser_provisioning._processes.clear()

    proc = await asyncio.create_subprocess_exec("sleep", "30")  # sleep exits on plain SIGTERM
    browser_provisioning._processes["well-behaved"] = proc

    await browser_provisioning._teardown("done", "ok")
    assert browser_provisioning.get_state()["cleanup_warning"] is None


async def test_download_chrome_times_out_with_a_clear_message(monkeypatch, tmp_path):
    import json as json_module

    monkeypatch.setattr(config, "GFMT_BROWSER_DOWNLOAD_TIMEOUT_S", 0.05)
    monkeypatch.setattr(browser_provisioning, "_runtime_dir", lambda: str(tmp_path))

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json_module.dumps({
                "channels": {"Stable": {"version": "1.2.3", "downloads": {"chrome": [
                    {"platform": "linux64", "url": "http://example.invalid/chrome-linux64.zip"},
                ]}}}
            }).encode()

    def fake_urlretrieve(url, path):
        time.sleep(0.5)  # comfortably longer than the timeout above

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **kw: _FakeResponse())
    monkeypatch.setattr(urllib.request, "urlretrieve", fake_urlretrieve)

    with pytest.raises(RuntimeError, match="Timed out after 0.05s downloading Chrome"):
        await browser_provisioning._download_chrome()


async def test_start_x_stack_raises_when_a_process_dies_immediately(monkeypatch):
    browser_provisioning._processes.clear()

    async def fake_exec(*args, **kwargs):
        # xvfb "starts" fine; x11vnc is the one a stale process left dead on arrival.
        return _FakeProc(returncode=None if args[0] == "Xvfb" else 1)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    try:
        with pytest.raises(RuntimeError, match="x11vnc exited immediately"):
            await browser_provisioning._start_x_stack()
    finally:
        # The fake procs stashed in the module-level _processes dict don't
        # have a real terminate()/wait() - clear them out so a later test's
        # app-shutdown teardown (if it ever runs with a stale "active" phase
        # left over from some other test) doesn't trip over them.
        browser_provisioning._processes.clear()


async def test_start_resets_stale_cleanup_warning(monkeypatch):
    browser_provisioning._state["cleanup_warning"] = "leftover from a previous attempt"
    browser_provisioning._state["phase"] = "idle"

    ran = asyncio.Event()

    async def fake_run_flow():
        ran.set()

    # start() kicks off _run_flow() as a real background task - stub it out so
    # this test never touches the real apt-get/Chrome-download flow.
    monkeypatch.setattr(browser_provisioning, "_run_flow", fake_run_flow)

    await browser_provisioning.start()
    assert browser_provisioning.get_state()["cleanup_warning"] is None

    await asyncio.wait_for(ran.wait(), timeout=2)


def _stub_out_stack(monkeypatch):
    """_run_flow's own concern is the sign-in state machine, not actually
    installing/downloading/launching anything - each of those three steps
    already has its own dedicated tests above. Stubbed as async no-ops here
    so the smoke tests below exercise only the orchestration."""

    async def fake_install_x_stack():
        pass

    async def fake_download_chrome():
        return "/fake/chrome"

    async def fake_start_x_stack():
        pass

    monkeypatch.setattr(browser_provisioning, "_install_x_stack", fake_install_x_stack)
    monkeypatch.setattr(browser_provisioning, "_download_chrome", fake_download_chrome)
    monkeypatch.setattr(browser_provisioning, "_start_x_stack", fake_start_x_stack)
    monkeypatch.setattr(browser_provisioning, "_runtime_dir", lambda: "/tmp")


async def test_run_flow_reaches_done_on_a_full_successful_sign_in(monkeypatch):
    """End-to-end smoke test of _run_flow's own state machine (install ->
    download -> launch -> sign in -> shared key -> teardown as "done") -
    the individual pieces are covered elsewhere; this is the one thing
    tying them together that wasn't covered by any single-function test."""
    browser_provisioning._chrome_bin = None
    browser_provisioning._processes.clear()
    browser_provisioning._state.update(phase="idle", message="", percent=0, error=None, cleanup_warning=None)

    _stub_out_stack(monkeypatch)

    cached_values = {"aas_token": "tok", "fcm_credentials": {"x": 1}, "shared_key": "key"}
    monkeypatch.setattr(browser_provisioning, "get_aas_token", lambda: "tok")
    monkeypatch.setattr(browser_provisioning, "get_shared_key", lambda: "key")
    monkeypatch.setattr(browser_provisioning, "get_cached_value", lambda name: cached_values.get(name))

    await browser_provisioning._run_flow()

    state = browser_provisioning.get_state()
    assert state["phase"] == "done"
    assert state["error"] is None


async def test_run_flow_reports_timeout_when_sign_in_never_completes(monkeypatch):
    browser_provisioning._chrome_bin = None
    browser_provisioning._processes.clear()
    browser_provisioning._state.update(phase="idle", message="", percent=0, error=None, cleanup_warning=None)

    _stub_out_stack(monkeypatch)
    monkeypatch.setattr(config, "GFMT_BROWSER_IDLE_TIMEOUT_S", 0.05)

    def never_signs_in():
        raise TimeoutError("Timed out waiting for the Google sign-in page.")

    monkeypatch.setattr(browser_provisioning, "get_aas_token", never_signs_in)
    monkeypatch.setattr(browser_provisioning, "get_cached_value", lambda name: None)

    await browser_provisioning._run_flow()

    state = browser_provisioning.get_state()
    assert state["phase"] == "timeout"
    assert "Google sign-in" in state["message"]
