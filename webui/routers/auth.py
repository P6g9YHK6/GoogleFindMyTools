import httpx
from fastapi import APIRouter, Request

from Auth.token_cache import get_cached_value
from webui import config
from webui.templating import templates

router = APIRouter()


def _auth_status() -> dict:
    aas_token = get_cached_value("aas_token")
    fcm_credentials = get_cached_value("fcm_credentials")
    username = get_cached_value("username")
    return {
        "logged_in": bool(aas_token and fcm_credentials),
        "username": username,
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
    async with httpx.AsyncClient() as client:
        response = await client.post(f"{config.BROWSER_AGENT_URL}/login/start", timeout=10)
        response.raise_for_status()
        return response.json()


@router.get("/auth/login/poll")
async def auth_login_poll():
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{config.BROWSER_AGENT_URL}/login/status", timeout=10)
        response.raise_for_status()
        return response.json()
