"""Tests for webui/browser_stack.py - installing/launching/killing the
Chrome/Xvfb/x11vnc/noVNC stack itself, independent of the sign-in state
machine built on top of it (see tests/test_browser_provisioning.py)."""

import asyncio
import time
import urllib.request

import pytest

from webui import browser_stack, config


class _FakeProc:
    """Stands in for an asyncio.subprocess.Process for kill_chrome's own
    pkill/pgrep calls (which it spawns internally), so this never shells out
    for real."""

    def __init__(self, returncode=0):
        self.returncode = returncode

    async def wait(self):
        return self.returncode


async def test_kill_chrome_confirms_clean_exit(monkeypatch):
    browser_stack._chrome_bin = "/fake/chrome"

    async def fake_exec(*args, **kwargs):
        if args[0] == "pkill":
            return _FakeProc(0)
        if args[0] == "pgrep":
            return _FakeProc(1)  # not found -> gone
        raise AssertionError(f"unexpected exec {args}")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    assert await browser_stack.kill_chrome() is None


async def test_kill_chrome_reports_stuck_process(monkeypatch):
    browser_stack._chrome_bin = "/fake/chrome"

    async def fake_exec(*args, **kwargs):
        if args[0] == "pkill":
            return _FakeProc(0)
        if args[0] == "pgrep":
            return _FakeProc(0)  # still found, every poll
        raise AssertionError(f"unexpected exec {args}")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    t0 = time.monotonic()
    result = await browser_stack.kill_chrome()
    dt = time.monotonic() - t0
    assert result == "Chrome"
    assert dt < 6  # bounded polling window, not an indefinite hang


async def test_teardown_reports_a_process_that_ignores_sigterm():
    browser_stack._chrome_bin = None  # isolate to the tracked-process path only
    browser_stack._processes.clear()

    proc = await asyncio.create_subprocess_exec(
        "python3", "-c", "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)",
    )
    try:
        await asyncio.sleep(0.3)  # let it install the signal handler before we terminate() it
        browser_stack._processes["stubborn"] = proc

        t0 = time.monotonic()
        unclean = await browser_stack.teardown()
        dt = time.monotonic() - t0

        assert dt < 6  # concurrent kill/wait, not stacked sequentially
        assert unclean == ["stubborn"]
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()


async def test_teardown_reports_nothing_when_everything_exits_cleanly():
    browser_stack._chrome_bin = None
    browser_stack._processes.clear()

    proc = await asyncio.create_subprocess_exec("sleep", "30")  # sleep exits on plain SIGTERM
    browser_stack._processes["well-behaved"] = proc

    assert await browser_stack.teardown() == []


async def test_teardown_clears_tracked_state():
    browser_stack._chrome_bin = "/fake/chrome"
    browser_stack._processes.clear()

    proc = await asyncio.create_subprocess_exec("sleep", "30")
    browser_stack._processes["well-behaved"] = proc

    await browser_stack.teardown()

    assert browser_stack._chrome_bin is None
    assert browser_stack._processes == {}


async def test_download_chrome_times_out_with_a_clear_message(monkeypatch, tmp_path):
    import json as json_module

    monkeypatch.setattr(config, "GFMT_BROWSER_DOWNLOAD_TIMEOUT_S", 0.05)
    monkeypatch.setattr(browser_stack, "_runtime_dir", lambda: str(tmp_path))

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
        await browser_stack.download_chrome()


async def test_start_x_stack_raises_when_a_process_dies_immediately(monkeypatch):
    browser_stack._processes.clear()

    async def fake_exec(*args, **kwargs):
        # xvfb "starts" fine; x11vnc is the one a stale process left dead on arrival.
        return _FakeProc(returncode=None if args[0] == "Xvfb" else 1)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    try:
        with pytest.raises(RuntimeError, match="x11vnc exited immediately"):
            await browser_stack.start_x_stack()
    finally:
        # The fake procs stashed in the module-level _processes dict don't
        # have a real terminate()/wait() - clear them out so a later test's
        # app-shutdown teardown (if it ever runs with a stale "active" phase
        # left over from some other test) doesn't trip over them.
        browser_stack._processes.clear()
