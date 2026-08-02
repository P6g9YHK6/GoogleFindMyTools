from fastapi import APIRouter, Request

from NovaApi.ListDevices.nbe_list_devices import request_device_list
from ProtoDecoders.decoder import get_canonic_ids, parse_device_list_protobuf
from SpotApi.UploadPrecomputedPublicKeyIds.upload_precomputed_public_key_ids import refresh_custom_trackers
from webui.deps import run_blocking
from webui.templating import templates

router = APIRouter()


async def get_devices() -> list[dict]:
    def _fetch():
        result_hex = request_device_list()
        device_list = parse_device_list_protobuf(result_hex)
        refresh_custom_trackers(device_list)
        return get_canonic_ids(device_list)

    canonic_ids = await run_blocking(_fetch)
    return [{"name": name, "canonic_id": canonic_id} for name, canonic_id in canonic_ids]


@router.get("/")
async def index(request: Request):
    return templates.TemplateResponse(request, "devices/list.html", {})


@router.get("/devices/table")
async def devices_table(request: Request):
    devices = await get_devices()
    return templates.TemplateResponse(request, "devices/_table.html", {"devices": devices})
