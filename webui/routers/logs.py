from datetime import datetime

from fastapi import APIRouter, Request

from webui.auth_state import is_logged_in
from webui.forwarders import log_store
from webui.templating import templates

router = APIRouter()


def _entries_for_display() -> list[dict]:
    entries = log_store.recent_entries()
    for entry in entries:
        entry["time_str"] = datetime.fromtimestamp(entry["time"]).strftime("%Y-%m-%d %H:%M:%S")
    return entries


@router.get("/logs")
async def logs_page(request: Request):
    if not is_logged_in():
        return templates.TemplateResponse(request, "_not_signed_in.html", {})
    return templates.TemplateResponse(request, "logs/list.html", {"entries": _entries_for_display()})
