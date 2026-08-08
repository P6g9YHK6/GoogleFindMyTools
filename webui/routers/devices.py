from datetime import datetime

from fastapi import APIRouter, Request

from NovaApi.ListDevices.nbe_list_devices import request_device_list
from ProtoDecoders.decoder import get_canonic_ids, parse_device_list_protobuf
from SpotApi.UploadPrecomputedPublicKeyIds.upload_precomputed_public_key_ids import refresh_custom_trackers
from webui import device_location_store
from webui.auth_state import is_logged_in
from webui.deps import run_blocking
from webui.templating import templates

router = APIRouter()


def _last_seen_from_persisted_locations(last: dict | None) -> int | None:
    """Fallback last-seen source for devices with no hardwareInfo.lastSeenTime
    (see ProtoDecoders/decoder.py:get_last_seen) - Spot/BLE tags don't carry
    that, and Google's own device-list response doesn't otherwise expose a
    tag's last-seen time until it's actively been located at least once
    (confirmed against a live account: the real web app only shows it after
    a manual locate, sourced from its own real-time push channel - a
    different, much more complex API this project doesn't implement). Using
    the most recent location we've actually fetched (manual click or cron)
    gets the same practical result without needing that.
    """
    if not last:
        return None
    times = [loc["time"] for loc in last["locations"] if not loc.get("is_semantic") and loc.get("time")]
    return max(times) if times else None


async def get_devices() -> list[dict]:
    def _fetch():
        result_hex = request_device_list()
        device_list = parse_device_list_protobuf(result_hex)
        refresh_custom_trackers(device_list)
        return get_canonic_ids(device_list)

    canonic_ids = await run_blocking(_fetch)

    devices = []
    for name, canonic_id, last_seen in canonic_ids:
        last = device_location_store.get_last_location(canonic_id)
        last_seen = last_seen or _last_seen_from_persisted_locations(last)
        extra_info = device_location_store.get_last_extra_info(canonic_id)
        devices.append({
            "name": name,
            "canonic_id": canonic_id,
            "last_locations": last["locations"] if last else None,
            "last_fetched_at_str": (
                datetime.fromtimestamp(last["fetched_at"]).strftime("%Y-%m-%d %H:%M:%S") if last else None
            ),
            "last_seen_str": datetime.fromtimestamp(last_seen).strftime("%Y-%m-%d %H:%M:%S") if last_seen else None,
            # Only ever set for devices with the "fetch_live_info" endpoint
            # toggle on - see Auth/live_device_info.py and webui/scheduler.py.
            "battery_pct": extra_info.get("battery_pct") if extra_info else None,
            "wifi_ssid": extra_info.get("wifi_ssid") if extra_info else None,
            "wifi_signal": extra_info.get("wifi_signal") if extra_info else None,
            "extra_info_fetched_at_str": (
                datetime.fromtimestamp(extra_info["fetched_at"]).strftime("%Y-%m-%d %H:%M:%S")
                if extra_info and extra_info.get("fetched_at") else None
            ),
        })
    return devices


@router.get("/")
async def index(request: Request):
    return templates.TemplateResponse(request, "devices/list.html", {})


@router.get("/devices/table")
async def devices_table(request: Request):
    if not is_logged_in():
        return templates.TemplateResponse(request, "_not_signed_in.html", {})
    devices = await get_devices()
    return templates.TemplateResponse(request, "devices/_table.html", {"devices": devices})
