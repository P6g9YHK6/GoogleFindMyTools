from fastapi import APIRouter, Request

from webui.deps import locate_device
from webui.templating import templates
from webui.ws import manager

router = APIRouter()


@router.post("/devices/{canonic_id}/locate")
async def locate(request: Request, canonic_id: str, name: str = ""):
    display_name = name or canonic_id
    locations = await locate_device(canonic_id, display_name)

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
