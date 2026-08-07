import yaml
from croniter import croniter
from fastapi import APIRouter, Form, HTTPException, Request

from NovaApi.ListDevices.nbe_list_devices import request_device_list
from ProtoDecoders.decoder import get_canonic_ids, parse_device_list_protobuf
from webui import scheduler
from webui.auth_state import is_logged_in
from webui.deps import run_blocking
from webui.forwarders import FORWARDER_TYPES, config_store
from webui.forwarders import blank_endpoint as new_blank_endpoint
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
    for google_name, canonic_id in canonic_ids:
        device_cfg = devices.get(canonic_id) or {"display_name": google_name, "endpoints": []}
        save_error = None
        if overrides and canonic_id in overrides:
            device_cfg = overrides[canonic_id]["config"]
            save_error = overrides[canonic_id]["error"]
        # The stored display_name is a user-set alias (Google's own device name is
        # sometimes cryptic/confusing) - fall back to Google's name until one is set.
        alias = device_cfg.get("display_name") or google_name
        rows.append({
            "name": alias,
            "google_name": google_name,
            "canonic_id": canonic_id,
            "config": device_cfg,
            "save_error": save_error,
        })
    return rows


async def _row(canonic_id: str, overrides: dict[str, dict] | None = None) -> dict:
    """The single row a device's own save POST should come back as - saving one
    device's form must not hand the browser the whole page's worth of forms to
    swap into that one form's slot (see _device_row.html)."""
    rows = await _rows(overrides=overrides)
    fallback = (overrides or {}).get(canonic_id, {})
    return next(
        (r for r in rows if r["canonic_id"] == canonic_id),
        {
            "name": fallback.get("config", {}).get("display_name", canonic_id),
            "google_name": None,
            "canonic_id": canonic_id,
            "config": fallback.get("config", {"endpoints": []}),
            "save_error": fallback.get("error"),
        },
    )


@router.get("/settings")
async def settings_page(request: Request):
    if not is_logged_in():
        return templates.TemplateResponse(request, "_not_signed_in.html", {})
    return templates.TemplateResponse(request, "settings/forwarding.html", {
        "rows": await _rows(), **_TEMPLATE_CONTEXT,
    })


@router.get("/settings/devices/{canonic_id}")
async def device_form_route(request: Request, canonic_id: str):
    """Re-renders just the structured form - the "Edit as form" button's
    target when switching back out of the YAML view below."""
    if not is_logged_in():
        return templates.TemplateResponse(request, "_not_signed_in.html", {})
    row = await _row(canonic_id)
    return templates.TemplateResponse(request, "settings/_device_form.html", {
        "row": row, **_TEMPLATE_CONTEXT,
    })


@router.get("/settings/devices/{canonic_id}/yaml")
async def device_yaml_route(request: Request, canonic_id: str):
    if not is_logged_in():
        return templates.TemplateResponse(request, "_not_signed_in.html", {})
    row = await _row(canonic_id)
    yaml_text = yaml.safe_dump(row["config"], sort_keys=False, allow_unicode=True)
    return templates.TemplateResponse(request, "settings/_device_yaml.html", {
        "canonic_id": canonic_id, "name": row["name"], "yaml_text": yaml_text,
    })


@router.post("/settings/devices/{canonic_id}/yaml")
async def save_device_yaml_route(request: Request, canonic_id: str, yaml_text: str = Form(...)):
    if not is_logged_in():
        return templates.TemplateResponse(request, "_not_signed_in.html", {})

    row = await _row(canonic_id)
    try:
        parsed = yaml.safe_load(yaml_text)
        if parsed is None:
            parsed = {}
        if not isinstance(parsed, dict):
            raise ValueError("must be a mapping (e.g. \"endpoints: [...]\"), not a list or a bare value")
        parsed.setdefault("endpoints", [])
        if not isinstance(parsed["endpoints"], list):
            raise ValueError("\"endpoints\" must be a list")
        for i, endpoint in enumerate(parsed["endpoints"]):
            if not isinstance(endpoint, dict):
                raise ValueError(f"endpoints[{i}] must be a mapping")
    except (yaml.YAMLError, ValueError) as e:
        return templates.TemplateResponse(request, "settings/_device_yaml.html", {
            "canonic_id": canonic_id, "name": row["name"], "yaml_text": yaml_text,
            "error": f"Invalid YAML: {e}",
        })

    parsed.setdefault("display_name", row["name"])
    config_store.set_device_config(canonic_id, parsed)
    scheduler.restart_device(canonic_id)

    fresh_row = await _row(canonic_id)
    return templates.TemplateResponse(request, "settings/_device_form.html", {
        "row": fresh_row, **_TEMPLATE_CONTEXT,
    })


@router.get("/settings/devices/{canonic_id}/endpoints/blank")
async def blank_endpoint_route(request: Request, canonic_id: str):
    if not is_logged_in():
        return templates.TemplateResponse(request, "_not_signed_in.html", {})

    blank = new_blank_endpoint(scheduler.DEFAULT_CRON)
    return templates.TemplateResponse(request, "settings/_endpoint_fields.html", {
        "endpoint": blank, **_TEMPLATE_CONTEXT,
    })


@router.post("/settings/devices/{canonic_id}/endpoints/{index}/send-now")
async def send_now_route(request: Request, canonic_id: str, index: int):
    if not is_logged_in():
        return templates.TemplateResponse(request, "_not_signed_in.html", {})

    endpoint = await scheduler.forward_now(canonic_id, index)
    if endpoint is None:
        raise HTTPException(status_code=404, detail="No such device or endpoint")

    # Rendered outside the per-device-row loop, so the "Send now" button (which
    # needs the device id and this endpoint's position) can't rely on `row`/
    # `loop.index0` being in scope the way the normal page render provides them
    # - pass both explicitly instead, so the swapped-in fragment can still be
    # sent again immediately.
    return templates.TemplateResponse(request, "settings/_endpoint_fields.html", {
        "endpoint": endpoint, "row": {"canonic_id": canonic_id}, "endpoint_index": index, **_TEMPLATE_CONTEXT,
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
    aliases = form.getlist("alias")
    skip_flags = form.getlist("skip_if_close")
    min_movements = form.getlist("min_movement_m")
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

        alias = (aliases[i] if i < len(aliases) else "").strip()
        if alias:
            entry["alias"] = alias

        cron_expr = (crons[i] if i < len(crons) else "").strip()
        if not cron_expr or not croniter.is_valid(cron_expr):
            errors.append(f"Endpoint {len(endpoints) + 1}: \"{cron_expr}\" is not a valid cron expression")
        entry["cron"] = cron_expr or scheduler.DEFAULT_CRON

        if (skip_flags[i] if i < len(skip_flags) else "0") == "1":
            entry["skip_if_close"] = True
            try:
                entry["min_movement_m"] = float(min_movements[i]) if i < len(min_movements) else scheduler.DEFAULT_MIN_MOVEMENT_M
            except ValueError:
                entry["min_movement_m"] = scheduler.DEFAULT_MIN_MOVEMENT_M

        # Best-effort: carry forward this endpoint's last status/position if it
        # still looks like the same logical endpoint at this position - these
        # just re-populate from scratch otherwise (a fresh save would otherwise
        # forget the last-sent position and always send the next fix).
        if i < len(existing_endpoints) and existing_endpoints[i].get("type") == etype:
            entry["last_forward_status"] = existing_endpoints[i].get("last_forward_status")
            entry["last_forward_time"] = existing_endpoints[i].get("last_forward_time")
            entry["last_sent_lat"] = existing_endpoints[i].get("last_sent_lat")
            entry["last_sent_lon"] = existing_endpoints[i].get("last_sent_lon")

        endpoints.append(entry)

    if errors:
        device_cfg = {"display_name": display_name, "endpoints": endpoints}
        row = await _row(canonic_id, overrides={canonic_id: {"config": device_cfg, "error": "; ".join(errors)}})
        return templates.TemplateResponse(request, "settings/_device_form.html", {
            "row": row, **_TEMPLATE_CONTEXT,
        })

    device_cfg = {"display_name": display_name, "endpoints": endpoints}
    config_store.set_device_config(canonic_id, device_cfg)
    scheduler.restart_device(canonic_id)

    row = await _row(canonic_id)
    return templates.TemplateResponse(request, "settings/_device_form.html", {
        "row": row, **_TEMPLATE_CONTEXT,
    })
