import logging

from fastapi import APIRouter, HTTPException, Request

from webui.deps import set_sound
from webui.templating import templates

logger = logging.getLogger("webui.sound")

router = APIRouter()


@router.post("/devices/{canonic_id}/sound/{action}")
async def sound(request: Request, canonic_id: str, action: str):
    if action not in ("start", "stop"):
        raise HTTPException(status_code=400, detail="action must be 'start' or 'stop'")

    try:
        await set_sound(canonic_id, action == "start")
    except Exception as e:
        # Used to just hand back whatever set_sound() raised/returned as
        # bare JSON - with no hx-target on the button that posted here,
        # htmx's default swap dumped that raw {"ok": true}/error text
        # straight into the button's own label. A small pass/fail glyph in
        # the dedicated status slot next to it (see devices/_table.html) is
        # what someone clicking "Play sound" actually wants to see instead.
        logger.exception("Sound %s failed for %s", action, canonic_id)
        return templates.TemplateResponse(request, "devices/_sound_status.html", {
            "ok": False, "error": str(e) or f"{type(e).__name__} (see server logs for details)",
        })
    return templates.TemplateResponse(request, "devices/_sound_status.html", {"ok": True})
