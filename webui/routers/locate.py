import logging
import time

from fastapi import APIRouter, Request

from webui import config, device_location_store
from webui.deps import locate_device, open_live_info_watch, run_blocking
from webui.forwarders import config_store
from webui.templating import templates
from webui.ws import manager

logger = logging.getLogger("webui.locate")

router = APIRouter()


def _wants_live_info(canonic_id: str) -> bool:
    """Same "fetch_live_info" toggle used for forwarding (Forwarding Settings
    page) - a manual Locate click populates the Devices page's live info too
    if any endpoint has it on, even though this click isn't itself a forward."""
    if not config.ENABLE_LIVE_DEVICE_INFO:
        return False
    device_cfg = config_store.get_device_config(canonic_id)
    endpoints = device_cfg.get("endpoints", []) if device_cfg else []
    return any(ep.get("fetch_live_info") for ep in endpoints)


@router.post("/devices/{canonic_id}/locate")
async def locate(request: Request, canonic_id: str, name: str = ""):
    display_name = name or canonic_id

    # The watch has to be open *before* the locate happens - see
    # Auth/live_device_info.py's module docstring.
    watch = await open_live_info_watch(canonic_id) if _wants_live_info(canonic_id) else None
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
        })

    if watch:
        extra_info = await run_blocking(watch.wait_for_update, 15.0)
        if extra_info:
            device_location_store.set_last_extra_info(canonic_id, extra_info, int(time.time()))

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
    })
