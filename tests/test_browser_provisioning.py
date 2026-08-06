import asyncio
import time

import webui.browser_provisioning as browser_provisioning


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
