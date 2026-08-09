"""Tests for webui/browser_provisioning.py's own concern: the sign-in state
machine (start/on_shutdown, and _run_flow's install -> download -> launch ->
sign in -> shared key -> teardown sequence). The browser stack it drives is
covered separately in tests/test_browser_stack.py."""

import asyncio

import pytest

import webui.browser_provisioning as browser_provisioning
from webui import browser_stack, config


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


async def test_teardown_surfaces_a_cleanup_warning_from_the_stack(monkeypatch):
    async def fake_teardown():
        return ["stubborn", "x11vnc"]

    monkeypatch.setattr(browser_stack, "teardown", fake_teardown)

    await browser_provisioning._teardown("error", "something went wrong")

    warning = browser_provisioning.get_state()["cleanup_warning"]
    assert "stubborn" in warning
    assert "x11vnc" in warning


async def test_teardown_reports_no_warning_when_the_stack_exits_cleanly(monkeypatch):
    async def fake_teardown():
        return []

    monkeypatch.setattr(browser_stack, "teardown", fake_teardown)

    await browser_provisioning._teardown("done", "ok")
    assert browser_provisioning.get_state()["cleanup_warning"] is None


def _stub_out_stack(monkeypatch, tmp_path):
    """_run_flow's own concern is the sign-in state machine, not actually
    installing/downloading/launching anything - each of those three steps
    already has its own dedicated tests in tests/test_browser_stack.py.
    Stubbed as async no-ops here so the smoke tests below exercise only the
    orchestration."""

    async def fake_install_x_stack(on_progress=None):
        pass

    async def fake_download_chrome(on_progress=None):
        return "/fake/chrome"

    async def fake_start_x_stack(on_progress=None):
        pass

    async def fake_teardown():
        return []

    monkeypatch.setattr(browser_stack, "install_x_stack", fake_install_x_stack)
    monkeypatch.setattr(browser_stack, "download_chrome", fake_download_chrome)
    monkeypatch.setattr(browser_stack, "start_x_stack", fake_start_x_stack)
    monkeypatch.setattr(browser_stack, "teardown", fake_teardown)
    # _run_flow makes its own runtime_dir/home_dir under this - the real
    # default (/run/gfmt-browser) isn't writable in a test environment.
    monkeypatch.setattr(config, "GFMT_BROWSER_RUNTIME_DIR", str(tmp_path))


async def test_run_flow_reaches_done_on_a_full_successful_sign_in(monkeypatch, tmp_path):
    """End-to-end smoke test of _run_flow's own state machine (install ->
    download -> launch -> sign in -> shared key -> teardown as "done") -
    the individual pieces are covered elsewhere; this is the one thing
    tying them together that wasn't covered by any single-function test."""
    browser_provisioning._state.update(phase="idle", message="", percent=0, error=None, cleanup_warning=None)

    _stub_out_stack(monkeypatch, tmp_path)

    cached_values = {"aas_token": "tok", "fcm_credentials": {"x": 1}, "shared_key": "key"}
    monkeypatch.setattr(browser_provisioning, "get_aas_token", lambda: "tok")
    monkeypatch.setattr(browser_provisioning, "get_shared_key", lambda: "key")
    monkeypatch.setattr(browser_provisioning, "get_cached_value", lambda name: cached_values.get(name))

    await browser_provisioning._run_flow()

    state = browser_provisioning.get_state()
    assert state["phase"] == "done"
    assert state["error"] is None


async def test_run_flow_reports_timeout_when_sign_in_never_completes(monkeypatch, tmp_path):
    browser_provisioning._state.update(phase="idle", message="", percent=0, error=None, cleanup_warning=None)

    _stub_out_stack(monkeypatch, tmp_path)
    monkeypatch.setattr(config, "GFMT_BROWSER_IDLE_TIMEOUT_S", 0.05)

    def never_signs_in():
        raise TimeoutError("Timed out waiting for the Google sign-in page.")

    monkeypatch.setattr(browser_provisioning, "get_aas_token", never_signs_in)
    monkeypatch.setattr(browser_provisioning, "get_cached_value", lambda name: None)

    await browser_provisioning._run_flow()

    state = browser_provisioning.get_state()
    assert state["phase"] == "timeout"
    assert "Google sign-in" in state["message"]


async def test_run_flow_reports_an_error_when_a_stack_step_raises(monkeypatch, tmp_path):
    browser_provisioning._state.update(phase="idle", message="", percent=0, error=None, cleanup_warning=None)
    _stub_out_stack(monkeypatch, tmp_path)

    async def broken_install(on_progress=None):
        raise RuntimeError("apt-get install failed")

    monkeypatch.setattr(browser_stack, "install_x_stack", broken_install)

    await browser_provisioning._run_flow()

    state = browser_provisioning.get_state()
    assert state["phase"] == "error"
    assert "apt-get install failed" in state["message"]


@pytest.fixture(autouse=True)
def _reset_browser_stack_state():
    """Belt-and-suspenders: whatever a test above sets on browser_stack's
    module-level process/chrome-binary tracking shouldn't leak into whatever
    runs next (e.g. the app-shutdown teardown other test files' `client`
    fixture triggers)."""
    yield
    browser_stack._processes.clear()
    browser_stack._chrome_bin = None
