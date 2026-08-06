from croniter import croniter
from fastapi import APIRouter, Form, Request

from NovaApi.ListDevices.nbe_list_devices import request_device_list
from ProtoDecoders.decoder import get_canonic_ids, parse_device_list_protobuf
from webui import scheduler
from webui.auth_state import is_logged_in
from webui.deps import run_blocking
from webui.forwarders import config_store
from webui.templating import templates

router = APIRouter()


async def _rows(overrides: dict[str, dict] | None = None) -> list[dict]:
    def _fetch():
        result_hex = request_device_list()
        device_list = parse_device_list_protobuf(result_hex)
        return get_canonic_ids(device_list)

    canonic_ids = await run_blocking(_fetch)
    devices = config_store.all_devices()

    rows = []
    for name, canonic_id in canonic_ids:
        device_cfg = devices.get(canonic_id) or {"display_name": name, "endpoints": []}
        row = {"name": name, "canonic_id": canonic_id, "config": device_cfg, "save_error": None}
        if overrides and canonic_id in overrides:
            row["config"] = overrides[canonic_id]["config"]
            row["save_error"] = overrides[canonic_id]["error"]
        rows.append(row)
    return rows


@router.get("/settings")
async def settings_page(request: Request):
    if not is_logged_in():
        return templates.TemplateResponse(request, "_not_signed_in.html", {})
    return templates.TemplateResponse(request, "settings/forwarding.html", {"rows": await _rows()})


@router.get("/settings/devices/{canonic_id}/endpoints/blank")
async def blank_endpoint(request: Request, canonic_id: str):
    if not is_logged_in():
        return templates.TemplateResponse(request, "_not_signed_in.html", {})

    blank = {"type": "traccar", "traccar": {}, "phonetrack": {}, "cron": scheduler.DEFAULT_CRON}
    return templates.TemplateResponse(request, "settings/_endpoint_fields.html", {"endpoint": blank})


@router.post("/settings/devices/{canonic_id}")
async def update_device_settings(
    request: Request,
    canonic_id: str,
    display_name: str = Form(...),
):
    if not is_logged_in():
        return templates.TemplateResponse(request, "_not_signed_in.html", {})

    form = await request.form()
    types = form.getlist("endpoint_type")
    crons = form.getlist("cron")
    traccar_urls = form.getlist("traccar_url")
    traccar_ids = form.getlist("traccar_device_id")
    phonetrack_urls = form.getlist("phonetrack_base_url")
    phonetrack_names = form.getlist("phonetrack_device_name")

    existing = config_store.get_device_config(canonic_id) or {"endpoints": []}
    existing_endpoints = existing.get("endpoints", [])

    endpoints = []
    errors = []
    for i, etype in enumerate(types):
        entry = {"type": etype}
        if etype == "traccar":
            url = traccar_urls[i] if i < len(traccar_urls) else ""
            if not url:
                continue  # unfilled "+ Add endpoint" block, drop it silently
            entry["traccar"] = {
                "url": url,
                "device_id": traccar_ids[i] if i < len(traccar_ids) else "",
            }
        elif etype == "phonetrack":
            url = phonetrack_urls[i] if i < len(phonetrack_urls) else ""
            if not url:
                continue
            entry["phonetrack"] = {
                "base_url": url,
                "device_name": phonetrack_names[i] if i < len(phonetrack_names) else "",
            }
        else:
            continue  # unknown/blank type, skip defensively

        cron_expr = (crons[i] if i < len(crons) else "").strip()
        if not cron_expr or not croniter.is_valid(cron_expr):
            errors.append(f"Endpoint {len(endpoints) + 1}: \"{cron_expr}\" is not a valid cron expression")
        entry["cron"] = cron_expr or scheduler.DEFAULT_CRON

        # Best-effort: carry forward this endpoint's last status if it still looks
        # like the same logical endpoint at this position - status just re-populates
        # on the next poll otherwise, so this isn't worth tracking more precisely.
        if i < len(existing_endpoints) and existing_endpoints[i].get("type") == etype:
            entry["last_forward_status"] = existing_endpoints[i].get("last_forward_status")
            entry["last_forward_time"] = existing_endpoints[i].get("last_forward_time")

        endpoints.append(entry)

    if errors:
        device_cfg = {"display_name": display_name, "endpoints": endpoints}
        rows = await _rows(overrides={canonic_id: {"config": device_cfg, "error": "; ".join(errors)}})
        return templates.TemplateResponse(request, "settings/forwarding.html", {"rows": rows})

    device_cfg = {"display_name": display_name, "endpoints": endpoints}
    config_store.set_device_config(canonic_id, device_cfg)
    scheduler.restart_device(canonic_id)

    return templates.TemplateResponse(request, "settings/forwarding.html", {"rows": await _rows()})
