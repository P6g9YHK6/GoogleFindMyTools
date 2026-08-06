from croniter import croniter
from fastapi import APIRouter, Form, Request

from NovaApi.ListDevices.nbe_list_devices import request_device_list
from ProtoDecoders.decoder import get_canonic_ids, parse_device_list_protobuf
from webui import scheduler
from webui.auth_state import is_logged_in
from webui.deps import run_blocking
from webui.forwarders import FORWARDER_TYPES, blank_endpoint as new_blank_endpoint, config_store
from webui.templating import templates

router = APIRouter()

_TEMPLATE_CONTEXT = {"forwarder_types": FORWARDER_TYPES}


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
    return templates.TemplateResponse(request, "settings/forwarding.html", {
        "rows": await _rows(), **_TEMPLATE_CONTEXT,
    })


@router.get("/settings/devices/{canonic_id}/endpoints/blank")
async def blank_endpoint_route(request: Request, canonic_id: str):
    if not is_logged_in():
        return templates.TemplateResponse(request, "_not_signed_in.html", {})

    blank = new_blank_endpoint(scheduler.DEFAULT_CRON)
    return templates.TemplateResponse(request, "settings/_endpoint_fields.html", {
        "endpoint": blank, **_TEMPLATE_CONTEXT,
    })


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
    # Grab every registered type's fields up front, keyed the same way the
    # template names its inputs (see ForwarderType.form_field_name) - adding a
    # new type to the registry is picked up here automatically, no new
    # getlist() calls to add.
    field_lists = {
        type_key: {f.name: form.getlist(ftype.form_field_name(f.name)) for f in ftype.fields}
        for type_key, ftype in FORWARDER_TYPES.items()
    }

    existing = config_store.get_device_config(canonic_id) or {"endpoints": []}
    existing_endpoints = existing.get("endpoints", [])

    endpoints = []
    errors = []
    for i, etype in enumerate(types):
        ftype = FORWARDER_TYPES.get(etype)
        if ftype is None:
            continue  # unknown/blank type, skip defensively

        cfg = {
            f.name: (values[i] if i < len(values) else "")
            for f, values in ((f, field_lists[etype][f.name]) for f in ftype.fields)
        }
        # The first configured field is always the destination's required
        # "address" (a URL) - treat a block as unfilled/blank if it's empty,
        # same as the old hardcoded traccar_url/phonetrack_base_url checks.
        if not cfg.get(ftype.fields[0].name):
            continue  # unfilled "+ Add endpoint" block, drop it silently

        entry = {"type": etype, etype: cfg}

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
        return templates.TemplateResponse(request, "settings/forwarding.html", {
            "rows": rows, **_TEMPLATE_CONTEXT,
        })

    device_cfg = {"display_name": display_name, "endpoints": endpoints}
    config_store.set_device_config(canonic_id, device_cfg)
    scheduler.restart_device(canonic_id)

    return templates.TemplateResponse(request, "settings/forwarding.html", {
        "rows": await _rows(), **_TEMPLATE_CONTEXT,
    })
