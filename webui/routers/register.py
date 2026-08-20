from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from webui import firmware_store
from webui.deps import register_tracker
from webui.templating import templates

router = APIRouter()


@router.get("/register")
async def register_form():
    # The standalone Register page is now the "Register Tracker" section at
    # the top of the Firmware page - redirect old links/bookmarks there
    # instead of serving a page that no longer exists on its own.
    return RedirectResponse("/firmware")


@router.post("/register")
async def register_submit(request: Request):
    result = await register_tracker()
    # Remember the (public) EID so the Firmware page can offer it again later
    # instead of requiring it be copy-pasted from this one-time display.
    firmware_store.record_registration(result["eid_hex"], result.get("pair_date", 0))
    return templates.TemplateResponse(request, "firmware/_register_result.html", {"result": result})
