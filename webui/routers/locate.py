import logging

from fastapi import APIRouter, Request

from webui.deps import locate_device
from webui.templating import templates
from webui.ws import manager

logger = logging.getLogger("webui.locate")

router = APIRouter()


@router.post("/devices/{canonic_id}/locate")
async def locate(request: Request, canonic_id: str, name: str = ""):
    display_name = name or canonic_id

    try:
        locations = await locate_device(canonic_id, display_name)
    except Exception as e:
        # Without this, any failure here (decrypt errors, expired tokens, a
        # network hiccup, ...) surfaced as a bare 500 with an empty "Last
        # locate result" cell - htmx doesn't swap error responses in by
        # default, so the real reason was only ever visible in server logs.
        logger.exception("Locate failed for %s", canonic_id)
        return templates.TemplateResponse(request, "devices/_locate_result.html", {
            "canonic_id": canonic_id,
            "name": display_name,
            "locations": None,
            "error": str(e) or f"{type(e).__name__} (see server logs for details)",
        })

    await manager.broadcast({
        "type": "locate_result",
        "canonic_id": canonic_id,
        "name": display_name,
        "locations": locations,
        "source": "manual",
    })

    return templates.TemplateResponse(request, "devices/_locate_result.html", {
        "canonic_id": canonic_id,
        "name": display_name,
        "locations": locations,
    })
