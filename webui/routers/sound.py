from fastapi import APIRouter, HTTPException

from webui.deps import set_sound

router = APIRouter()


@router.post("/devices/{canonic_id}/sound/{action}")
async def sound(canonic_id: str, action: str):
    if action not in ("start", "stop"):
        raise HTTPException(status_code=400, detail="action must be 'start' or 'stop'")

    return await set_sound(canonic_id, action == "start")
