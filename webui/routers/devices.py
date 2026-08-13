import json
from datetime import datetime

from fastapi import APIRouter, Request

from NovaApi.ListDevices.nbe_list_devices import request_device_list
from ProtoDecoders.decoder import get_canonic_ids, parse_device_list_protobuf
from SpotApi.UploadPrecomputedPublicKeyIds.upload_precomputed_public_key_ids import refresh_custom_trackers
from webui import device_location_store, scheduler, settings_store
from webui.auth_state import is_logged_in
from webui.deps import run_blocking
from webui.device_list_cache import device_list_cache
from webui.forwarders import config_store
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


def _next_poll(canonic_id: str) -> datetime | None:
    """Soonest upcoming poll across this device's configured endpoints, for
    the Devices page - reuses scheduler._next_run directly (the same
    function the real poll loop waits on, see webui/scheduler.py's
    _poll_device) so this can never disagree with when a poll actually
    fires. None if the device has no endpoints configured, or none of them
    have a valid cron."""
    device_cfg = config_store.get_device_config(canonic_id)
    endpoints = device_cfg.get("endpoints") if device_cfg else None
    if not endpoints:
        return None
    now = datetime.now()
    next_runs = [scheduler._next_run(ep.get("cron", scheduler.DEFAULT_CRON), now) for ep in endpoints]
    valid_next_runs = [t for t in next_runs if t is not None]
    if not valid_next_runs:
        return None
    return min(valid_next_runs)


def _next_poll_str(canonic_id: str) -> str | None:
    next_poll = _next_poll(canonic_id)
    return next_poll.strftime("%Y-%m-%d %H:%M:%S") if next_poll else None


async def get_devices() -> list[dict]:
    def _fetch():
        result_hex = request_device_list()
        device_list = parse_device_list_protobuf(result_hex)
        refresh_custom_trackers(device_list)
        return get_canonic_ids(device_list)

    canonic_ids = await run_blocking(device_list_cache.get_or_fetch, _fetch)
    # Loaded once for the whole page, not per device - a page-load-time
    # display preference, not a per-device or per-endpoint setting (see
    # settings_store.py; unrelated to forwarding's own per-endpoint
    # only_most_recent toggle in webui/forwarders/policy.py).
    most_recent_only_display = settings_store.load().get("devices_page_most_recent_only")

    devices = []
    for name, canonic_id, last_seen in canonic_ids:
        last = device_location_store.get_last_location(canonic_id)
        # _last_seen_from_persisted_locations must stay correct regardless
        # of the display preference below, so it reads last["locations"]
        # unfiltered - only what's actually shown ("last_locations") is
        # narrowed down.
        last_seen = last_seen or _last_seen_from_persisted_locations(last)
        next_poll = _next_poll(canonic_id)
        # The local nickname (if any - see webui/routers/settings.py) and how
        # many forwarding endpoints are configured, straight off the same
        # forwarding config _next_poll above already reads per device.
        device_cfg = config_store.get_device_config(canonic_id)
        last_locations = last["locations"] if last else None
        if last_locations and most_recent_only_display:
            last_locations = device_location_store.most_recent_only(last_locations)
        devices.append({
            "name": name,
            "canonic_id": canonic_id,
            "alias": device_cfg.get("display_name") if device_cfg else None,
            "endpoint_count": len(device_cfg.get("endpoints") or []) if device_cfg else 0,
            "last_locations": last_locations,
            "last_fetched_at_str": (
                datetime.fromtimestamp(last["fetched_at"]).strftime("%Y-%m-%d %H:%M:%S") if last else None
            ),
            "last_seen_str": datetime.fromtimestamp(last_seen).strftime("%Y-%m-%d %H:%M:%S") if last_seen else None,
            "next_poll_str": next_poll.strftime("%Y-%m-%d %H:%M:%S") if next_poll else None,
            # Raw epoch seconds alongside the formatted string above, for the
            # live countdown static/app.js ticks down client-side (see
            # devices/_table.html's data-next-poll-ts) - a formatted string
            # alone can't be recomputed against "now" every second.
            "next_poll_ts": int(next_poll.timestamp()) if next_poll else None,
        })
    return devices


@router.get("/")
async def index(request: Request):
    return templates.TemplateResponse(request, "devices/list.html", {})


def _map_devices_json(devices: list[dict]) -> str:
    """Feeds devices/_table.html's inline script, which seeds the map with
    each device's last known locations on page load (see static/app.js's
    seedMapMarkers) - trimmed to just what the map needs instead of reusing
    the full `devices` context (next-poll times, etc. would just be dead
    weight in the page's HTML)."""
    payload = [
        {"canonic_id": d["canonic_id"], "name": d["name"], "locations": d["last_locations"] or []}
        for d in devices
    ]
    return json.dumps(payload, default=str).replace("</", "<\\/")


@router.get("/devices/table")
async def devices_table(request: Request):
    if not is_logged_in():
        return templates.TemplateResponse(request, "_not_signed_in.html", {})
    devices = await get_devices()
    return templates.TemplateResponse(
        request, "devices/_table.html", {"devices": devices, "map_devices_json": _map_devices_json(devices)}
    )
