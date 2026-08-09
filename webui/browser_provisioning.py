"""The web login flow's sign-in state machine: what phase it's in, what
message/percent to show, and when to tear the browser stack back down.
Installing/launching/killing the actual Chrome/Xvfb/x11vnc/noVNC stack is
webui/browser_stack.py's job - this module only decides *when* to call into
it and what to tell the Config page while it's happening.
"""

import asyncio
import logging
import os

from Auth import auth_flow
from Auth.aas_token_retrieval import get_aas_token
from Auth.token_cache import get_cached_value
from KeyBackup.shared_key_retrieval import get_shared_key
from webui import browser_stack, config
from webui.ws import provision_manager

logger = logging.getLogger("webui.browser_provisioning")

_ACTIVE_PHASES = {"starting", "installing", "downloading", "extracting", "launching", "ready", "logging_in"}

_state = {"phase": "idle", "message": "", "percent": 0, "error": None, "cleanup_warning": None}


def get_state() -> dict:
    return dict(_state)


def is_active() -> bool:
    return _state["phase"] in _ACTIVE_PHASES


async def start() -> dict:
    if _state["phase"] in _ACTIVE_PHASES:
        return {"started": False, "state": get_state()}

    # Clear any warning left over from a previous attempt's teardown - the
    # Config page should only ever reflect the most recent one.
    _state["cleanup_warning"] = None
    await _set_state("starting", "Starting...", 0)
    asyncio.create_task(_run_flow())
    return {"started": True, "state": get_state()}


async def on_shutdown():
    if _state["phase"] in _ACTIVE_PHASES:
        await _teardown("error", "Shut down while provisioning.")


async def _set_state(phase: str, message: str, percent: int, error: str | None = None):
    _state.update(phase=phase, message=message, percent=percent, error=error)
    await provision_manager.broadcast({"type": "provision", **_state})


async def _run_flow():
    try:
        await browser_stack.install_x_stack(on_progress=_set_state)
        chrome_bin = await browser_stack.download_chrome(on_progress=_set_state)
        await browser_stack.start_x_stack(on_progress=_set_state)

        runtime_dir = config.GFMT_BROWSER_RUNTIME_DIR
        os.makedirs(runtime_dir, exist_ok=True)
        home_dir = os.path.join(runtime_dir, "home")
        os.makedirs(home_dir, exist_ok=True)
        os.environ["GFMT_CHROME_BINARY"] = chrome_bin
        os.environ["GFMT_NONINTERACTIVE"] = "1"
        os.environ["HOME"] = home_dir

        await _set_state(
            "ready",
            f"Ready - complete the Google sign-in below within {auth_flow.SIGN_IN_WAIT_S // 60} minutes.",
            95,
        )

        logged_in = False
        timeout_message = None
        try:
            await asyncio.wait_for(
                asyncio.to_thread(get_aas_token),
                timeout=config.GFMT_BROWSER_IDLE_TIMEOUT_S,
            )
            account_signed_in = bool(get_cached_value("aas_token") and get_cached_value("fcm_credentials"))

            if account_signed_in:
                # Locating a device also needs a "shared key" to decrypt its
                # end-to-end encrypted location reports, which requires its own
                # separate Google sign-in (see KeyBackup/shared_key_flow.py) -
                # do it now, in the same browser/VNC session, rather than
                # leaving it to fail later the first time something calls
                # locate_device outside of any browser session at all.
                await _set_state(
                    "logging_in",
                    "Signed in. Google needs one more confirmation to allow decrypting "
                    f"end-to-end encrypted location reports - complete it below within "
                    f"{auth_flow.SIGN_IN_WAIT_S // 60} minutes.",
                    97,
                )
                await asyncio.wait_for(
                    asyncio.to_thread(get_shared_key),
                    timeout=config.GFMT_BROWSER_IDLE_TIMEOUT_S,
                )
                logged_in = bool(get_cached_value("shared_key"))
        except TimeoutError as e:
            # Note: since Python 3.11, asyncio.TimeoutError *is* TimeoutError, so this
            # catches both the sign-in flows' own "you took too long" TimeoutErrors
            # (each with its own specific message, whichever step it came from) and
            # asyncio.wait_for's outer safety-net timeout (which doesn't) - fall back
            # to a generic message only for the latter, rather than showing a blank
            # or misleading one for either.
            timeout_message = str(e) or (
                f"Timed out waiting for sign-in - no sign-in activity detected within "
                f"{config.GFMT_BROWSER_IDLE_TIMEOUT_S}s of the browser being ready. "
                f"Click \"Sign in with Google\" again to retry."
            )

        if logged_in:
            await _teardown("done", "Signed in successfully. Removing the temporary browser...")
        elif timeout_message:
            await _teardown("timeout", timeout_message)
        else:
            await _teardown("timeout", "Sign-in did not complete. Click \"Sign in with Google\" again to retry.")
    except Exception as e:
        logger.exception("Browser provisioning failed")
        detail = str(e) or "no further details available, check server logs"
        await _teardown(
            "error",
            f"Provisioning failed ({type(e).__name__}): {detail}",
            error=str(e),
        )


async def _teardown(final_phase: str, message: str, error: str | None = None):
    """Ends one sign-in attempt: stops the browser stack (see
    webui/browser_stack.py's teardown() for what that does and doesn't
    clean up) and surfaces a warning on the Config page if anything had to
    be force-killed."""
    unclean = await browser_stack.teardown()
    _state["cleanup_warning"] = (
        f"{', '.join(unclean)} did not exit cleanly after the last sign-in and had to be "
        "force-killed. If this keeps happening, restart the container."
    ) if unclean else None

    await _set_state(final_phase, message, 100, error)
