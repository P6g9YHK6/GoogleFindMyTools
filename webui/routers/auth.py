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
    }


@router.get("/auth")
async def auth_page(request: Request):
    return templates.TemplateResponse(request, "auth/login.html", {
        "status": _auth_status(),
    })


@router.get("/auth/status")
async def auth_status():
    return _auth_status()


@router.post("/auth/login/start")
async def auth_login_start():
    return await browser_provisioning.start()


@router.get("/auth/login/poll")
async def auth_login_poll():
    return browser_provisioning.get_state()
