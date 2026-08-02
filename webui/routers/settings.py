from fastapi import APIRouter, Form, Request

from NovaApi.ListDevices.nbe_list_devices import request_device_list
from ProtoDecoders.decoder import get_canonic_ids, parse_device_list_protobuf
from webui import config, scheduler
from webui.auth_state import is_logged_in
from webui.deps import run_blocking
from webui.forwarders import config_store
from webui.templating import templates

router = APIRouter()


async def _rows() -> list[dict]:
    def _fetch():
        result_hex = request_device_list()
        device_list = parse_device_list_protobuf(result_hex)
        return get_canonic_ids(device_list)

    canonic_ids = await run_blocking(_fetch)
    devices = config_store.all_devices()

    rows = []
    for name, canonic_id in canonic_ids:
        device_cfg = devices.get(canonic_id) or {
            "display_name": name,
            "destination": "none",
            "poll_interval_seconds": config.DEFAULT_POLL_INTERVAL_S,
        }
        rows.append({"name": name, "canonic_id": canonic_id, "config": device_cfg})
    return rows


@router.get("/settings")
async def settings_page(request: Request):
    if not is_logged_in():
        return templates.TemplateResponse(request, "_not_signed_in.html", {})
    return templates.TemplateResponse(request, "settings/forwarding.html", {"rows": await _rows()})


@router.post("/settings/devices/{canonic_id}")
async def update_device_settings(
    request: Request,
    canonic_id: str,
    display_name: str = Form(...),
    destination: str = Form("none"),
    poll_interval_seconds: int = Form(300),
    traccar_url: str = Form(""),
    traccar_device_id: str = Form(""),
    phonetrack_base_url: str = Form(""),
    phonetrack_device_name: str = Form(""),
):
    if not is_logged_in():
        return templates.TemplateResponse(request, "_not_signed_in.html", {})

    device_cfg = {
        "display_name": display_name,
        "destination": destination,
        "poll_interval_seconds": poll_interval_seconds,
        "traccar": {"url": traccar_url, "device_id": traccar_device_id},
        "phonetrack": {"base_url": phonetrack_base_url, "device_name": phonetrack_device_name},
    }
    config_store.set_device_config(canonic_id, device_cfg)
    scheduler.restart_device(canonic_id)

    return templates.TemplateResponse(request, "settings/forwarding.html", {"rows": await _rows()})
