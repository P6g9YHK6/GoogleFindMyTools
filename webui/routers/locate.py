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
        # No oob_swaps here - a failure doesn't touch what's persisted (see
        # the "A timeout/empty result must never clobber..." comment below),
        # so the separate Map/Polled-at columns (see _locate_cell.html) must
        # stay exactly as they were, not get OOB-replaced with this
        # response's own empty `locations`.
        return templates.TemplateResponse(request, "devices/_locate_cell.html", {
            "canonic_id": canonic_id,
            "name": display_name,
            "locations": None,
            "error": str(e) or f"{type(e).__name__} (see server logs for details)",
        })

    fetched_at = int(time.time())
    fetched_at_str = None
    oob_swaps = False
    if locations:
        # A timeout/empty result must never clobber the last real fix
        # already on file - only persist an actual location, and only then
        # OOB-swap the Map/Polled-at columns (see _locate_cell.html) - for
        # the same reason as the error branch above, an empty result here
        # must leave both exactly as they were instead of blanking them out.
        device_location_store.set_last_location(canonic_id, locations, fetched_at)
        fetched_at_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(fetched_at))
        oob_swaps = True

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
        "oob_swaps": oob_swaps,
    })
