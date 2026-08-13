import logging
import time

from fastapi import APIRouter, Request

from webui import device_location_store
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
        return templates.TemplateResponse(request, "devices/_locate_cell.html", {
            "canonic_id": canonic_id,
            "name": display_name,
            "locations": None,
            "error": str(e) or f"{type(e).__name__} (see server logs for details)",
            # Out-of-band-swaps the separate "Map" column too (see
            # _locate_cell.html) - only set on this standalone-render path,
            # never when included as part of the whole table, or the OOB
            # <div> would show up as a second, duplicate-id copy of the map
            # links sitting inertly in the "Last locate result" cell.
            "oob_map_links": True,
        })

    fetched_at = int(time.time())
    fetched_at_str = None
    if locations:
        # A timeout/empty result must never clobber the last real fix
        # already on file - only persist an actual location.
        device_location_store.set_last_location(canonic_id, locations, fetched_at)
        fetched_at_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(fetched_at))

    await manager.broadcast({
        "type": "locate_result",
        "canonic_id": canonic_id,
        "name": display_name,
        "locations": locations,
        "source": "manual",
    })

    return templates.TemplateResponse(request, "devices/_locate_cell.html", {
        "canonic_id": canonic_id,
        "name": display_name,
        "locations": locations,
        "fetched_at_str": fetched_at_str,
        "oob_map_links": True,  # see the comment on the error branch above
    })
