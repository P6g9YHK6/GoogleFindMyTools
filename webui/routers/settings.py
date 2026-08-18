import json

import yaml
from croniter import croniter
from fastapi import APIRouter, Form, HTTPException, Request

from webui import scheduler
from webui.auth_state import is_logged_in
from webui.forwarders import (
    BUILTIN_VARIABLES_FROM_APP,
    BUILTIN_VARIABLES_FROM_FIX,
    PRESETS,
    config_store,
    device_label_variables,
    latest_values_store,
    policy,
    settings_service,
)
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
    "presets": PRESETS, "presets_json": _PRESETS_JSON,
    "builtin_variables_from_fix": BUILTIN_VARIABLES_FROM_FIX,
    "builtin_variables_from_app": BUILTIN_VARIABLES_FROM_APP,
    "cron_presets": scheduler.CRON_PRESETS, "cron_preset_values": {value for _, value in scheduler.CRON_PRESETS},
    "status_choices": policy.STATUS_CHOICES,
}


@router.get("/settings")
async def settings_page(request: Request):
    if not is_logged_in():
        return templates.TemplateResponse(request, "_not_signed_in.html", {})
    return templates.TemplateResponse(request, "settings/forwarding.html", {
        "rows": await settings_service.rows(), **_TEMPLATE_CONTEXT,
    })


@router.get("/settings/devices/{canonic_id}")
async def device_form_route(request: Request, canonic_id: str):
    """Re-renders just the structured form from whatever's on disk - kept
    around as a plain "load the saved config" route, though the "Edit as
    form" button no longer uses it (see device_form_preview_route below,
    which reflects not-yet-saved YAML edits instead)."""
    if not is_logged_in():
        return templates.TemplateResponse(request, "_not_signed_in.html", {})
    row = await settings_service.row(canonic_id)
    return templates.TemplateResponse(request, "settings/_device_form.html", {
        "row": row, **_TEMPLATE_CONTEXT,
    })


@router.get("/settings/devices/{canonic_id}/yaml")
async def device_yaml_route(request: Request, canonic_id: str):
    """Plain "load the saved config as YAML" route - the "Edit as YAML"
    button no longer uses this either (see device_yaml_preview_route
    below), for the same reason as device_form_route above."""
    if not is_logged_in():
        return templates.TemplateResponse(request, "_not_signed_in.html", {})
    row = await settings_service.row(canonic_id)
    yaml_text = yaml.safe_dump(
        settings_service.to_yaml_doc(row["config"].get("display_name", ""), row["config"].get("endpoints", [])),
        sort_keys=False, allow_unicode=True,
    )
    return templates.TemplateResponse(request, "settings/_device_yaml.html", {
        "canonic_id": canonic_id, "name": row["name"], "google_name": row["google_name"],
        "alias": row["config"].get("display_name") or "", "yaml_text": yaml_text,
        "label_variables": row["label_variables"], **_TEMPLATE_CONTEXT,
    })


@router.post("/settings/devices/{canonic_id}/yaml/preview")
async def device_yaml_preview_route(request: Request, canonic_id: str, display_name: str = Form("")):
    """The "Edit as YAML" button's actual target: converts the form's
    current field values - including whatever's been typed but not yet
    saved - into YAML, entirely in memory. Switching views this way never
    needs a Save first and never throws unsaved edits away by re-reading
    the last-saved config instead (which is all the plain GET above could
    do)."""
    if not is_logged_in():
        return templates.TemplateResponse(request, "_not_signed_in.html", {})

    form = await request.form()
    existing = config_store.get_device_config(canonic_id) or {"endpoints": []}
    endpoints, _errors = settings_service.parse_endpoints_form(form, existing.get("endpoints", []))
    yaml_text = yaml.safe_dump(settings_service.to_yaml_doc(display_name, endpoints), sort_keys=False, allow_unicode=True)
    # The heading is always the fixed Google name (falling back to the
    # just-typed alias, then canonic_id, only when google_name is itself
    # unknown) - same rule as _device_form.html's own legend. The alias
    # shows too, small, next to it - see _device_yaml.html.
    google_name = existing.get("google_name") or ""
    name = google_name or display_name.strip() or canonic_id
    return templates.TemplateResponse(request, "settings/_device_yaml.html", {
        "canonic_id": canonic_id, "name": name, "google_name": google_name, "alias": display_name.strip(),
        "yaml_text": yaml_text,
        "label_variables": device_label_variables(existing.get("device_meta")), **_TEMPLATE_CONTEXT,
    })


@router.post("/settings/devices/{canonic_id}/form/preview")
async def device_form_preview_route(request: Request, canonic_id: str, yaml_text: str = Form(...)):
    """The YAML view's "Edit as form" button's actual target - the mirror
    image of device_yaml_preview_route above: parses whatever's currently
    typed in the YAML textarea - including its display_name - back into
    the form, without saving it."""
    if not is_logged_in():
        return templates.TemplateResponse(request, "_not_signed_in.html", {})

    existing = config_store.get_device_config(canonic_id) or {}
    endpoints, display_name, error = settings_service.from_yaml_doc(yaml_text)
    if error:
        google_name = existing.get("google_name") or ""
        name = google_name or existing.get("display_name") or canonic_id
        return templates.TemplateResponse(request, "settings/_device_yaml.html", {
            "canonic_id": canonic_id, "name": name, "google_name": google_name,
            "alias": existing.get("display_name") or "", "yaml_text": yaml_text,
            "error": error, "label_variables": device_label_variables(existing.get("device_meta")), **_TEMPLATE_CONTEXT,
        })

    device_cfg = {"display_name": display_name, "endpoints": endpoints}
    row = await settings_service.row(canonic_id, overrides={canonic_id: {"config": device_cfg, "error": None}})
    return templates.TemplateResponse(request, "settings/_device_form.html", {
        "row": row, **_TEMPLATE_CONTEXT,
    })


@router.post("/settings/devices/{canonic_id}/yaml")
async def save_device_yaml_route(request: Request, canonic_id: str, yaml_text: str = Form(...)):
    if not is_logged_in():
        return templates.TemplateResponse(request, "_not_signed_in.html", {})

    row = await settings_service.row(canonic_id)
    endpoints, display_name, error = settings_service.from_yaml_doc(yaml_text)
    if error:
        return templates.TemplateResponse(request, "settings/_device_yaml.html", {
            "canonic_id": canonic_id, "name": row["name"], "google_name": row["google_name"],
            "alias": row["config"].get("display_name") or "", "yaml_text": yaml_text,
            "error": error, "label_variables": row["label_variables"], **_TEMPLATE_CONTEXT,
        })

    # The form path (update_device_settings below) has always rejected an
    # invalid cron rather than saving it - this path let one through
    # unchecked, silently breaking that endpoint's polling (or the whole
    # device's, if every endpoint's cron was bad) with no error shown.
    cron_errors = [
        f"endpoints[{i}]: \"{ep.get('cron', '')}\" is not a valid cron expression"
        for i, ep in enumerate(endpoints)
        if not croniter.is_valid(str(ep.get("cron", "")))
    ]
    if cron_errors:
        return templates.TemplateResponse(request, "settings/_device_yaml.html", {
            "canonic_id": canonic_id, "name": row["name"], "google_name": row["google_name"],
            "alias": row["config"].get("display_name") or "", "yaml_text": yaml_text,
            "error": "; ".join(cron_errors), "label_variables": row["label_variables"], **_TEMPLATE_CONTEXT,
        })

    # google_name isn't part of what this editor shows (see to_yaml_doc) -
    # carry it forward from what's already on disk instead of losing it.
    # display_name *is* part of what this editor shows, so whatever was
    # just typed here is what gets saved, same as the form's own alias
    # field would.
    existing = config_store.get_device_config(canonic_id)
    device_cfg = {"display_name": display_name, "endpoints": endpoints}
    if existing and existing.get("google_name"):
        device_cfg["google_name"] = existing["google_name"]
    # device_meta isn't part of what this editor shows either (see
    # to_yaml_doc) - same reason as google_name just above: carry it
    # forward too, or this device's label_* chips go missing until the
    # next page load's sync happens to run again.
    if existing and existing.get("device_meta"):
        device_cfg["device_meta"] = existing["device_meta"]

    try:
        config_store.set_device_config(canonic_id, device_cfg)
        scheduler.restart_device(canonic_id)
    except Exception as e:
        return templates.TemplateResponse(request, "settings/_device_yaml.html", {
            "canonic_id": canonic_id, "name": row["name"], "google_name": row["google_name"],
            "alias": row["config"].get("display_name") or "", "yaml_text": yaml_text,
            "error": f"Failed to save: {e}", "label_variables": row["label_variables"], **_TEMPLATE_CONTEXT,
        })
    latest_values_store.prune_to_urls(canonic_id, {ep["url"] for ep in endpoints})

    fresh_row = await settings_service.row(canonic_id, saved=True)
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
    # Rendered outside the per-device-row loop (same reason as send_now_route
    # below), so `row` isn't in scope the normal way either - a bare stub
    # just carrying label_variables lets the "From the location fix" chip
    # list still reflect this device's real data on a brand-new block. Safe
    # against the template's only other row-gated behavior (the "Send now"
    # button) since that's already conditioned on "not is_new" too, and
    # is_new is always True here.
    device_meta = (config_store.get_device_config(canonic_id) or {}).get("device_meta")
    return templates.TemplateResponse(request, "settings/_endpoint_fields.html", {
        "endpoint": blank, "idx": "__NEW__", "is_new": True,
        "row": {"label_variables": device_label_variables(device_meta)},
        **_TEMPLATE_CONTEXT,
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
    # sent again immediately. label_variables is included too so the chip
    # list still reflects this device's real data after the swap.
    device_meta = (config_store.get_device_config(canonic_id) or {}).get("device_meta")
    return templates.TemplateResponse(request, "settings/_endpoint_fields.html", {
        "endpoint": endpoint,
        "row": {"canonic_id": canonic_id, "label_variables": device_label_variables(device_meta)},
        "idx": str(index), "send_error": send_error, **_TEMPLATE_CONTEXT,
    })


@router.post("/settings/devices/{canonic_id}")
async def update_device_settings(
    request: Request,
    canonic_id: str,
    display_name: str = Form(""),
):
    if not is_logged_in():
        return templates.TemplateResponse(request, "_not_signed_in.html", {})

    form = await request.form()
    existing = config_store.get_device_config(canonic_id) or {"endpoints": []}
    endpoints, errors = settings_service.parse_endpoints_form(form, existing.get("endpoints", []))

    # google_name/device_meta aren't fields this form ever edits (see
    # settings_service.rows' own Google-sync comment) - carry them forward
    # from what's already on disk rather than just building
    # {display_name, endpoints} and letting them go missing until the next
    # page load's sync happens to run again. Without this, a plain settings
    # save (e.g. just typing an alias) wiped google_name too, and
    # {{device_name}} fell back to that alias instead of staying the fixed
    # Google account name.
    device_cfg = {"display_name": display_name, "endpoints": endpoints}
    if existing.get("google_name"):
        device_cfg["google_name"] = existing["google_name"]
    if existing.get("device_meta"):
        device_cfg["device_meta"] = existing["device_meta"]

    if errors:
        row = await settings_service.row(canonic_id, overrides={canonic_id: {"config": device_cfg, "error": "; ".join(errors)}})
        return templates.TemplateResponse(request, "settings/_device_form.html", {
            "row": row, **_TEMPLATE_CONTEXT,
        })

    try:
        config_store.set_device_config(canonic_id, device_cfg)
        scheduler.restart_device(canonic_id)
    except Exception as e:
        row = await settings_service.row(canonic_id, overrides={canonic_id: {"config": device_cfg, "error": f"Failed to save: {e}"}})
        return templates.TemplateResponse(request, "settings/_device_form.html", {
            "row": row, **_TEMPLATE_CONTEXT,
        })
    latest_values_store.prune_to_urls(canonic_id, {ep["url"] for ep in endpoints})

    row = await settings_service.row(canonic_id, saved=True)
    return templates.TemplateResponse(request, "settings/_device_form.html", {
        "row": row, **_TEMPLATE_CONTEXT,
    })
