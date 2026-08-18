from fastapi import APIRouter, Request

from webui import firmware_store
from webui.deps import register_tracker
from webui.templating import templates

router = APIRouter()


@router.get("/register")
async def register_form(request: Request):
    return templates.TemplateResponse(request, "register/form.html", {})


@router.post("/register")
async def register_submit(request: Request):
    result = await register_tracker()
    # Remember the (public) EID so the Firmware page can offer it again later
    # instead of requiring it be copy-pasted from this one-time display.
    firmware_store.record_registration(result["eid_hex"], result.get("pair_date", 0))
    return templates.TemplateResponse(request, "register/form.html", {"result": result})
