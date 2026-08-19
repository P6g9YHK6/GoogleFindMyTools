import json
from datetime import datetime

from fastapi import APIRouter, Request

from NovaApi.ListDevices.nbe_list_devices import request_device_list
from ProtoDecoders.decoder import get_device_details, parse_device_list_protobuf
from SpotApi.UploadPrecomputedPublicKeyIds.upload_precomputed_public_key_ids import refresh_custom_trackers
from webui import device_location_store, scheduler, settings_store
from webui.auth_state import is_logged_in
from webui.deps import run_blocking
from webui.device_list_cache import device_list_cache
from webui.forwarders import config_store
from webui.templating import templates

router = APIRouter()

# (emoji, plain label) per ProtoDecoders.DeviceUpdate_pb2.SpotDeviceType name
# (Spot/BLE tags only - phones don't carry this, see device_type_plain_label
# below). Kept here rather than in the decoder, which stays presentation-
# agnostic and just hands back the raw enum name. The plain label (no
# emoji) is also what {{type}} resolves to for forwarding templates (see
# webui/forwarders/custom.py) - an emoji has no business in a URL/header
# sent to a third-party service, so it's split out rather than stripped
# back out of the UI string at forward time.
_DEVICE_TYPE_LABELS = {
    "DEVICE_TYPE_BEACON": ("📡", "Beacon"),
    "DEVICE_TYPE_HEADPHONES": ("🎧", "Headphones"),
    "DEVICE_TYPE_KEYS": ("🔑", "Keys"),
    "DEVICE_TYPE_WATCH": ("⌚", "Watch"),
    "DEVICE_TYPE_WALLET": ("👛", "Wallet"),
    "DEVICE_TYPE_BAG": ("🎒", "Bag"),
    "DEVICE_TYPE_LAPTOP": ("💻", "Laptop"),
    "DEVICE_TYPE_CAR": ("🚗", "Car"),
    "DEVICE_TYPE_REMOTE_CONTROL": ("🎮", "Remote control"),
    "DEVICE_TYPE_BADGE": ("🪪", "Badge"),
    "DEVICE_TYPE_BIKE": ("🚲", "Bike"),
    "DEVICE_TYPE_CAMERA": ("📷", "Camera"),
    "DEVICE_TYPE_CAT": ("🐱", "Cat"),
    "DEVICE_TYPE_CHARGER": ("🔌", "Charger"),
    "DEVICE_TYPE_CLOTHING": ("👕", "Clothing"),
    "DEVICE_TYPE_DOG": ("🐶", "Dog"),
    "DEVICE_TYPE_NOTEBOOK": ("📓", "Notebook"),
    "DEVICE_TYPE_PASSPORT": ("🛂", "Passport"),
    "DEVICE_TYPE_PHONE": ("📱", "Phone"),
    "DEVICE_TYPE_SPEAKER": ("🔊", "Speaker"),
    "DEVICE_TYPE_TABLET": ("📱", "Tablet"),
    "DEVICE_TYPE_TOY": ("🧸", "Toy"),
    "DEVICE_TYPE_UMBRELLA": ("☂️", "Umbrella"),
    "DEVICE_TYPE_STYLUS": ("🖊️", "Stylus"),
    "DEVICE_TYPE_EARBUDS": ("🎧", "Earbuds"),
    "DEVICE_TYPE_LUGGAGE": ("🧳", "Luggage"),
}


def device_type_plain_label(device_type: str | None, is_phone: bool) -> str | None:
    """Just "Beacon"/"Phone"/etc, no emoji - what {{type}} resolves to for
    forwarding templates (see webui/forwarders/custom.py) and what
    _device_type_label below decorates for the UI."""
    if is_phone:
        return "Phone"
    if not device_type:
        return None
    if device_type in _DEVICE_TYPE_LABELS:
        return _DEVICE_TYPE_LABELS[device_type][1]
    # Unmapped (DEVICE_TYPE_UNKNOWN, or a type added to Google's schema
    # after this list was last updated) - a readable fallback beats a
    # crash or a blank cell/value.
    return device_type.removeprefix("DEVICE_TYPE_").replace("_", " ").title()


def _device_type_label(device_type: str | None, is_phone: bool) -> str | None:
    """UI-only decoration of device_type_plain_label above, with an emoji
    up front - see devices/_table.html's "Device" column."""
    plain = device_type_plain_label(device_type, is_phone)
    if plain is None:
        return None
    if is_phone:
        return f"📱 {plain}"
    # device_type is guaranteed non-None here (device_type_plain_label above
    # already returned non-None with is_phone False, which only happens when
    # device_type itself was truthy) - the "or ''" is just to satisfy .get()'s
    # str-only key type.
    emoji = _DEVICE_TYPE_LABELS.get(device_type or "", ("🏷️", ""))[0]
    return f"{emoji} {plain}"


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
        return get_device_details(device_list)

    device_details = await run_blocking(device_list_cache.get_or_fetch, _fetch)
    # Loaded once for the whole page, not per device - a page-load-time
    # display preference, not a per-device or per-endpoint setting (see
    # settings_store.py; unrelated to forwarding's own per-endpoint
    # only_most_recent toggle in webui/forwarders/policy.py).
    most_recent_only_display = settings_store.load().get("devices_page_most_recent_only")

    devices = []
    for detail in device_details:
        canonic_id = detail["canonic_id"]
        last = device_location_store.get_last_location(canonic_id)
        # _last_seen_from_persisted_locations must stay correct regardless
        # of the display preference below, so it reads last["locations"]
        # unfiltered - only what's actually shown ("last_locations") is
        # narrowed down.
        last_seen = detail["last_seen"] or _last_seen_from_persisted_locations(last)
        next_poll = _next_poll(canonic_id)
        # The local nickname (if any - see webui/routers/settings.py) and how
        # many forwarding endpoints are configured, straight off the same
        # forwarding config _next_poll above already reads per device.
        device_cfg = config_store.get_device_config(canonic_id)
        last_locations = last["locations"] if last else None
        if last_locations and most_recent_only_display:
            last_locations = device_location_store.most_recent_only(last_locations)
        # Sharing/ownership info (see ProtoDecoders.decoder.get_device_details)
        # - "Owner only" for the common case (just your own account, isOwner
        # true) rather than listing yourself back to yourself.
        shared_with = [a["email"] for a in detail["access"] if not a["this_account"]]
        devices.append({
            "name": detail["name"],
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
            # Device metadata from Google's own response - see
            # ProtoDecoders.decoder.get_device_details and this module's
            # _device_type_label. image_url/manufacturer/model/carrier/
            # codename/imei/registered_at_str are None when Google doesn't
            # report them (e.g. no hardwareInfo for a Spot/BLE tag).
            "image_url": detail["image_url"],
            "type_label": _device_type_label(detail["device_type"], detail["is_phone"]),
            "manufacturer": detail["manufacturer"],
            "model": detail["model"],
            "carrier": detail["carrier"],
            "codename": detail["codename"],
            "imei": detail["imei"],
            "registered_at_str": (
                datetime.fromtimestamp(detail["registered_at"]).strftime("%Y-%m-%d %H:%M:%S")
                if detail["registered_at"] else None
            ),
            "shared_with": shared_with,
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
