from fastapi import APIRouter, Request

from Auth.fcm_receiver import FcmReceiver
from Auth.token_cache import clear_all_cached_values, get_cached_value
from webui import browser_provisioning
from webui.auth_state import is_logged_in
from webui.deps import query_gate
from webui.templating import templates

router = APIRouter()

# Every credential the sign-in flow can produce - shown as a per-key present/
# missing breakdown on the account page instead of just one pass/fail bit, so
# a partial failure (e.g. aas_token cached but fcm_credentials never got
# written) is visible at a glance instead of needing to shell in and read
# secrets.json by hand to find out, as happened repeatedly while chasing that
# exact bug.
_DIAGNOSTIC_KEYS = ["username", "aas_token", "fcm_credentials", "shared_key", "owner_key"]


def _auth_status() -> dict:
    return {
        "logged_in": is_logged_in(),
        "username": get_cached_value("username"),
        # The account sign-in and the E2EE shared-key confirmation are two
        # separate steps (see webui/browser_provisioning.py) - surface both,
        # since being "logged in" alone doesn't mean locate will work yet.
        "shared_key_ready": get_cached_value("shared_key") is not None,
        "diagnostics": [
            {"name": name, "present": get_cached_value(name) is not None}
            for name in _DIAGNOSTIC_KEYS
        ],
        # Set if the browser/X11 processes from the last sign-in attempt
        # didn't all exit cleanly on their own - see _teardown() in
        # webui/browser_provisioning.py.
        "cleanup_warning": browser_provisioning.get_state().get("cleanup_warning"),
    }


@router.get("/auth")
async def auth_page(request: Request):
    return templates.TemplateResponse(request, "auth/login.html", {
        "status": _auth_status(),
    })


@router.get("/auth/queue")
async def auth_queue_status(request: Request):
    # Polled independently of /auth/status (see auth/login.html) - the queue
    # depth changes far more often than sign-in status, and shouldn't compete
    # with the sign-in flow's own hx-swaps into #login-status.
    return templates.TemplateResponse(request, "auth/_queue_status.html", {
        "waiting": query_gate.waiting,
    })


@router.get("/auth/status")
async def auth_status(request: Request):
    # Returns the same HTML fragment used on /auth (not raw JSON) - its only
    # caller is the "Refresh status" button's hx-get/hx-swap into #login-status.
    return templates.TemplateResponse(request, "auth/_status.html", {
        "status": _auth_status(),
    })


@router.post("/auth/clear")
async def auth_clear(request: Request):
    if browser_provisioning.is_active():
        # Clearing mid-flow is exactly how the "aas_token present but
        # fcm_credentials missing" split-brain state kept happening: a sign-in
        # already past its own FCM registration step gets its cache wiped out
        # from under it, then goes on to write a fresh aas_token into the now-
        # empty file with nothing left to re-populate fcm_credentials. Refuse
        # instead, matching the same guard start() already uses.
        return templates.TemplateResponse(request, "auth/_status.html", {
            "status": _auth_status(),
            "clear_error": "A sign-in is currently in progress - let it finish, time out, "
                            "or fail before clearing credentials.",
        })

    clear_all_cached_values()
    # FcmReceiver is an in-process singleton that reads fcm_credentials from
    # the cache once, at first use, and never again - clearing the file alone
    # would leave it silently serving its old in-memory copy forever, so the
    # very next sign-in would look successful but never actually re-register
    # (exactly the bug chased earlier: aas_token comes back fine, fcm_credentials
    # never does, with no error either time). Reset it too so a fresh sign-in
    # right after this button actually starts clean.
    FcmReceiver().clear()
    return templates.TemplateResponse(request, "auth/_status.html", {
        "status": _auth_status(),
    })


@router.post("/auth/login/start")
async def auth_login_start():
    return await browser_provisioning.start()


@router.get("/auth/login/poll")
async def auth_login_poll():
    return browser_provisioning.get_state()
