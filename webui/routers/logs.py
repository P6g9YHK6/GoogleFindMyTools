from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from webui import system_log_store
from webui.auth_state import is_logged_in
from webui.forwarders import log_store
from webui.templating import templates

router = APIRouter()

TYPE_FORWARDING = "forwarding"
TYPE_SYSTEM = "system"

# Union of both stores' level vocabularies (forwarding: ok/error/skipped,
# system: the five Python logging levels) - each already has a matching
# .log-<level> CSS class, so the two can share one "Level" column/filter.
LEVEL_CHOICES = ["ok", "error", "skipped", "info", "warning", "critical", "debug"]


def _forwarding_entries() -> list[dict]:
    entries = []
    for e in log_store.recent_entries():
        entries.append({
            "time": e["time"],
            "type": TYPE_FORWARDING,
            "type_label": "Forwarding",
            "level": e["level"],
            "level_label": e["level"].upper(),
            "source": e["device_name"],
            # endpoint_type used to always be the literal "custom" (every
            # endpoint's now-removed "type" field - see routers/settings.py's
            # _parse_endpoints_form) and never said anything a human didn't
            # already know; skip the "custom → " prefix entirely rather than
            # print a stale value for old log lines or a blank one for new.
            "detail": f"{e['target']}: {e['status']}",
            "payload": e.get("payload", ""),
        })
    return entries


def _system_entries() -> list[dict]:
    entries = []
    for e in system_log_store.recent_entries():
        entries.append({
            "time": e["time"],
            "type": TYPE_SYSTEM,
            "type_label": "System",
            "level": e["level"].lower(),
            "level_label": e["level"],
            "source": e["logger"],
            "detail": e["message"],
            "payload": "",
        })
    return entries


def _filters_from_request(request: Request) -> dict:
    params = request.query_params
    return {
        "type": params.get("type") or "all",
        "level": params.get("level") or "all",
        "q": params.get("q") or "",
    }


def _matching_entries(filters: dict) -> list[dict]:
    entries = []
    if filters["type"] in ("all", TYPE_FORWARDING):
        entries += _forwarding_entries()
    if filters["type"] in ("all", TYPE_SYSTEM):
        entries += _system_entries()
    entries.sort(key=lambda e: e["time"], reverse=True)

    if filters["level"] != "all":
        entries = [e for e in entries if e["level"] == filters["level"]]

    query = filters["q"].strip().lower()
    if query:
        entries = [
            e for e in entries
            if query in " ".join([e["source"], e["detail"], e["payload"], e["type_label"]]).lower()
        ]

    for e in entries:
        e["time_str"] = datetime.fromtimestamp(e["time"]).strftime("%Y-%m-%d %H:%M:%S")

    # Same "most recent N" cap the two separate pages already applied.
    return entries[:500]


def _has_active_filters(filters: dict) -> bool:
    return filters["type"] != "all" or filters["level"] != "all" or bool(filters["q"].strip())


@router.get("/logs")
async def logs_page(request: Request):
    if not is_logged_in():
        return templates.TemplateResponse(request, "_not_signed_in.html", {})
    filters = _filters_from_request(request)
    return templates.TemplateResponse(request, "logs/list.html", {
        "entries": _matching_entries(filters),
        "filters": filters,
        "level_choices": LEVEL_CHOICES,
        "has_active_filters": _has_active_filters(filters),
    })


@router.get("/logs/table")
async def logs_table(request: Request):
    """Partial re-render of just the table, for the filter form's live
    (htmx) updates - see logs/list.html."""
    if not is_logged_in():
        return templates.TemplateResponse(request, "_not_signed_in.html", {})
    filters = _filters_from_request(request)
    return templates.TemplateResponse(request, "logs/_table.html", {
        "entries": _matching_entries(filters),
        "has_active_filters": _has_active_filters(filters),
    })


@router.get("/logs/system")
async def system_log_redirect(request: Request):
    """The System Log used to be its own page - now folded into /logs
    (type=system), kept as a redirect for anyone with the old URL bookmarked."""
    return RedirectResponse(url="/logs?type=system", status_code=307)
