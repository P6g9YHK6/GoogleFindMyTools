from fastapi import APIRouter, Request

from Auth.token_cache import get_cached_value
from webui import browser_provisioning
from webui.auth_state import is_logged_in
from webui.templating import templates

router = APIRouter()


def _auth_status() -> dict:
    return {
        "logged_in": is_logged_in(),
        "username": get_cached_value("username"),
        # The account sign-in and the E2EE shared-key confirmation are two
        # separate steps (see webui/browser_provisioning.py) - surface both,
        # since being "logged in" alone doesn't mean locate will work yet.
        "shared_key_ready": get_cached_value("shared_key") is not None,
    }


@router.get("/auth")
async def auth_page(request: Request):
    return templates.TemplateResponse(request, "auth/login.html", {
        "status": _auth_status(),
    })


@router.get("/auth/status")
async def auth_status(request: Request):
    # Returns the same HTML fragment used on /auth (not raw JSON) - its only
    # caller is the "Refresh status" button's hx-get/hx-swap into #login-status.
    return templates.TemplateResponse(request, "auth/_status.html", {
        "status": _auth_status(),
    })


@router.post("/auth/login/start")
async def auth_login_start():
    return await browser_provisioning.start()


@router.get("/auth/login/poll")
async def auth_login_poll():
    return browser_provisioning.get_state()
