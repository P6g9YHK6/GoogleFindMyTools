import json

import yaml
from croniter import croniter
from fastapi import APIRouter, Form, HTTPException, Request

from NovaApi.ListDevices.nbe_list_devices import request_device_list
from ProtoDecoders.decoder import get_canonic_ids, parse_device_list_protobuf
from webui import scheduler
from webui.auth_state import is_logged_in
from webui.deps import run_blocking
from webui.forwarders import BUILTIN_VARIABLES, PRESETS, config_store, policy
from webui.forwarders import blank_endpoint as new_blank_endpoint
from webui.templating import templates

router = APIRouter()

# The client-side preset switcher (endpoint_fields.js) needs the same preset
# data the form itself was rendered with - embedded once as JSON rather than
# duplicated by hand in the JS file, so the two can't drift apart. Escaping
# "</" defensively guards against a preset value that happens to contain
# "</script" ending the block early - see forwarding.html's <script type=
# "application/json"> tag, which must not be HTML-escaped (its content is
# read back as raw JSON text, not markup) or this substitution would be
# pointless.
_PRESETS_JSON = json.dumps(PRESETS).replace("</", "<\\/")

_TEMPLATE_CONTEXT = {
    "presets": PRESETS, "builtin_variables": BUILTIN_VARIABLES, "presets_json": _PRESETS_JSON,
    "cron_presets": scheduler.CRON_PRESETS, "cron_preset_values": {value for _, value in scheduler.CRON_PRESETS},
}


async def _rows(overrides: dict[str, dict] | None = None, saved_id: str | None = None) -> list[dict]:
    def _fetch():
        result_hex = request_device_list()
        device_list = parse_device_list_protobuf(result_hex)
        return get_canonic_ids(device_list)

    canonic_ids = await run_blocking(_fetch)
    devices = config_store.all_devices()

    rows = []
    for google_name, canonic_id, _last_seen in canonic_ids:
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
            "saved": canonic_id == saved_id,
        })
    return rows


async def _row(canonic_id: str, overrides: dict[str, dict] | None = None, saved: bool = False) -> dict:
    """The single row a device's own save POST should come back as - saving one
    device's form must not hand the browser the whole page's worth of forms to
    swap into that one form's slot (see _device_row.html)."""
    rows = await _rows(overrides=overrides, saved_id=canonic_id if saved else None)
    fallback = (overrides or {}).get(canonic_id, {})
    return next(
        (r for r in rows if r["canonic_id"] == canonic_id),
        {
            "name": fallback.get("config", {}).get("display_name", canonic_id),
            "google_name": None,
            "canonic_id": canonic_id,
            "config": fallback.get("config", {"endpoints": []}),
            "save_error": fallback.get("error"),
            "saved": saved,
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

    # The form path (update_device_settings below) has always rejected an
    # invalid cron rather than saving it - this path let one through
    # unchecked, silently breaking that endpoint's polling (or the whole
    # device's, if every endpoint's cron was bad) with no error shown.
    cron_errors = [
        f"endpoints[{i}]: \"{ep.get('cron', '')}\" is not a valid cron expression"
        for i, ep in enumerate(parsed["endpoints"])
        if not croniter.is_valid(str(ep.get("cron", "")))
    ]
    if cron_errors:
        return templates.TemplateResponse(request, "settings/_device_yaml.html", {
            "canonic_id": canonic_id, "name": row["name"], "yaml_text": yaml_text,
            "error": "; ".join(cron_errors),
        })

    parsed.setdefault("display_name", row["name"])
    try:
        config_store.set_device_config(canonic_id, parsed)
        scheduler.restart_device(canonic_id)
    except Exception as e:
        return templates.TemplateResponse(request, "settings/_device_yaml.html", {
            "canonic_id": canonic_id, "name": row["name"], "yaml_text": yaml_text,
            "error": f"Failed to save: {e}",
        })

    fresh_row = await _row(canonic_id, saved=True)
    return templates.TemplateResponse(request, "settings/_device_form.html", {
        "row": fresh_row, **_TEMPLATE_CONTEXT,
    })


@router.post("/settings/cron-preview")
async def cron_preview_route(request: Request):
    """Backs the schedule editor's live "next run" feedback (see
    _endpoint_fields.html's .cron-raw input, which posts here via
    hx-include="this"). Reads whatever single field got posted rather than
    expecting one named "cron" - the real field is namespaced
    "ep-{idx}-cron" per endpoint (see update_device_settings below), and
    this route has no reason to care which one. Stateless and device-
    agnostic, so it works the same whether the endpoint being edited is
    already saved or a not-yet-submitted "+ Add endpoint" block."""
    form = await request.form()
    cron = next(iter(form.values()), "")
    preview = scheduler.cron_preview(str(cron))
    return templates.TemplateResponse(request, "settings/_cron_preview.html", {"preview": preview})


@router.get("/settings/devices/{canonic_id}/endpoints/blank")
async def blank_endpoint_route(request: Request, canonic_id: str):
    if not is_logged_in():
        return templates.TemplateResponse(request, "_not_signed_in.html", {})

    blank = new_blank_endpoint(scheduler.DEFAULT_CRON)
    return templates.TemplateResponse(request, "settings/_endpoint_fields.html", {
        "endpoint": blank, "idx": "__NEW__", "is_new": True, **_TEMPLATE_CONTEXT,
    })


@router.post("/settings/devices/{canonic_id}/endpoints/{index}/send-now")
async def send_now_route(request: Request, canonic_id: str, index: int):
    if not is_logged_in():
        return templates.TemplateResponse(request, "_not_signed_in.html", {})

    send_error = None
    try:
        endpoint = await scheduler.forward_now(canonic_id, index)
    except Exception as e:
        # forward_now already turns a failed *send* into a "error: ..."
        # last_forward_status string (see webui/forwarders/policy.py) - this
        # only catches a genuine failure to persist that result (e.g. a disk
        # write error), which would otherwise propagate to an uncaught 500
        # and leave the button looking like it silently did nothing.
        endpoint = None
        send_error = f"Send failed: {e}"

    if endpoint is None:
        if send_error is None:
            raise HTTPException(status_code=404, detail="No such device or endpoint")
        # Still re-render the block (with whatever's currently saved) so the
        # error has somewhere to show up, instead of a bare 500.
        device_cfg = config_store.get_device_config(canonic_id) or {}
        endpoints = device_cfg.get("endpoints", [])
        if not (0 <= index < len(endpoints)):
            raise HTTPException(status_code=404, detail="No such device or endpoint")
        endpoint = endpoints[index]

    # Rendered outside the per-device-row loop, so the "Send now" button (which
    # needs the device id and this endpoint's position) can't rely on `row`/
    # `loop.index0` being in scope the way the normal page render provides them
    # - pass both explicitly instead, so the swapped-in fragment can still be
    # sent again immediately.
    return templates.TemplateResponse(request, "settings/_endpoint_fields.html", {
        "endpoint": endpoint, "row": {"canonic_id": canonic_id}, "idx": str(index),
        "send_error": send_error, **_TEMPLATE_CONTEXT,
    })


def _parse_kv_rows(keys: list[str], values: list[str]) -> dict:
    return {k.strip(): v for k, v in zip(keys, values) if k.strip()}


@router.post("/settings/devices/{canonic_id}")
async def update_device_settings(
    request: Request,
    canonic_id: str,
    display_name: str = Form(...),
):
    if not is_logged_in():
        return templates.TemplateResponse(request, "_not_signed_in.html", {})

    form = await request.form()
    # Every endpoint block's fields are namespaced "ep-{idx}-{field}", with
    # idx unique per block (its saved position, or a fresh client-generated
    # id for one just added via "+ Add endpoint" - see endpoint_fields.js).
    # That, rather than one flat getlist() per field name shared across every
    # endpoint, is what lets each block carry its own variable-length headers
    # table without the rows of one block bleeding into another's.
    ep_order = form.getlist("ep_order")

    existing = config_store.get_device_config(canonic_id) or {"endpoints": []}
    existing_endpoints = existing.get("endpoints", [])

    endpoints = []
    errors = []
    for idx in ep_order:
        def field(name: str, default: str = "") -> str:
            return form.get(f"ep-{idx}-{name}", default) or default

        def field_list(name: str) -> list[str]:
            return form.getlist(f"ep-{idx}-{name}")

        url = field("url").strip()
        if not url:
            continue  # unfilled "+ Add endpoint" block, drop it silently

        entry = {
            # A preset (see the "Preset" dropdown, only ever shown on a
            # brand-new "+ Add endpoint" block - webui/forwarders/presets.py)
            # is a one-time template for starting an endpoint, never a saved
            # property of one - whatever the dropdown said (if it was even
            # posted at all) is ignored here.
            "type": "custom",
            "method": (field("method", "GET").strip().upper() or "GET"),
            "url": url,
            "headers": _parse_kv_rows(field_list("header_key"), field_list("header_value")),
            "body_type": field("body_type", "none").strip() or "none",
            "body": field("body"),
        }

        alias = field("alias").strip()
        if alias:
            entry["alias"] = alias

        cron_expr = field("cron").strip()
        if not cron_expr or not croniter.is_valid(cron_expr):
            errors.append(f"Endpoint {len(endpoints) + 1}: \"{cron_expr}\" is not a valid cron expression")
        entry["cron"] = cron_expr or scheduler.DEFAULT_CRON

        if field("skip_if_close", "0") == "1":
            entry["skip_if_close"] = True
            try:
                entry["min_movement_m"] = float(field("min_movement_m") or policy.DEFAULT_MIN_MOVEMENT_M)
            except ValueError:
                entry["min_movement_m"] = policy.DEFAULT_MIN_MOVEMENT_M

        if field("skip_if_stale", "0") == "1":
            entry["skip_if_stale"] = True
            try:
                entry["min_update_gap_m"] = float(field("min_update_gap_m") or policy.DEFAULT_MIN_UPDATE_GAP_M)
            except ValueError:
                entry["min_update_gap_m"] = policy.DEFAULT_MIN_UPDATE_GAP_M

        # Best-effort: carry forward this endpoint's last status/position (and
        # any leftover "variables", from before the settings UI dropped the
        # "Custom variables" table - there's no field left to re-post one, so
        # without this a save would silently erase e.g. a Traccar endpoint's
        # device_id) if it still looks like the same logical endpoint (same
        # position, same URL) - these just re-populate from scratch
        # otherwise (a fresh save would otherwise forget the last-sent
        # position and always send the next fix).
        position = len(endpoints)
        if position < len(existing_endpoints) and existing_endpoints[position].get("url") == url:
            for key in (
                "last_forward_status", "last_forward_time",
                "last_sent_lat", "last_sent_lon", "last_sent_fix_time",
                "variables",
            ):
                if key in existing_endpoints[position]:
                    entry[key] = existing_endpoints[position][key]

        endpoints.append(entry)

    if errors:
        device_cfg = {"display_name": display_name, "endpoints": endpoints}
        row = await _row(canonic_id, overrides={canonic_id: {"config": device_cfg, "error": "; ".join(errors)}})
        return templates.TemplateResponse(request, "settings/_device_form.html", {
            "row": row, **_TEMPLATE_CONTEXT,
        })

    device_cfg = {"display_name": display_name, "endpoints": endpoints}
    try:
        config_store.set_device_config(canonic_id, device_cfg)
        scheduler.restart_device(canonic_id)
    except Exception as e:
        row = await _row(canonic_id, overrides={canonic_id: {"config": device_cfg, "error": f"Failed to save: {e}"}})
        return templates.TemplateResponse(request, "settings/_device_form.html", {
            "row": row, **_TEMPLATE_CONTEXT,
        })

    row = await _row(canonic_id, saved=True)
    return templates.TemplateResponse(request, "settings/_device_form.html", {
        "row": row, **_TEMPLATE_CONTEXT,
    })
