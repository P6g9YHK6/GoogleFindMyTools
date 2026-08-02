from fastapi import APIRouter, Request

from webui.deps import register_tracker
from webui.templating import templates

router = APIRouter()


@router.get("/register")
async def register_form(request: Request):
    return templates.TemplateResponse(request, "register/form.html", {})


@router.post("/register")
async def register_submit(request: Request):
    result = await register_tracker()
    return templates.TemplateResponse(request, "register/form.html", {"result": result})
