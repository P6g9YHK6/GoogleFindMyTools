import asyncio
import json
import logging
import time
from datetime import datetime

from croniter import croniter

from webui import device_location_store, ws
from webui.auth_state import is_logged_in
from webui.deps import locate_device, open_live_info_watch, run_blocking
from webui.forwarders import FORWARDER_TYPES, config_store, log_store
from webui.geo import haversine_distance_m

logger = logging.getLogger("webui.scheduler")

_tasks: dict[str, asyncio.Task] = {}

DEFAULT_CRON = "*/5 * * * *"
DEFAULT_MIN_MOVEMENT_M = 50
DEFAULT_MIN_UPDATE_GAP_M = 30
# A fix this recent is treated as a genuinely live update rather than Google
# re-serving the same stale cached report - always sent regardless of the
# stale-duplicate gate below.
FRESH_FIX_AGE_S = 120


def _next_run(cron_expr: str, base: datetime) -> datetime | None:
    try:
        return croniter(cron_expr, base).get_next(datetime)
    except Exception as e:
        logger.warning("Invalid cron expression %r: %s", cron_expr, e)
        return None


def _too_close_to_bother(endpoint_cfg: dict, location: dict) -> bool:
    """True if this endpoint's "skip if it hasn't moved" toggle is on and the
    new fix is under its configured minimum-movement threshold from the last
    position actually sent - see webui/geo.py for the (local, API-free)
    distance calculation."""
    if not endpoint_cfg.get("skip_if_close"):
        return False
    if location.get("is_semantic") or location.get("latitude") is None:
        return False
    last_lat, last_lon = endpoint_cfg.get("last_sent_lat"), endpoint_cfg.get("last_sent_lon")
    if last_lat is None or last_lon is None:
        return False  # nothing sent yet for this endpoint - always send the first fix
    threshold = endpoint_cfg.get("min_movement_m") or DEFAULT_MIN_MOVEMENT_M
    return haversine_distance_m(last_lat, last_lon, location["latitude"], location["longitude"]) < threshold


def _stale_duplicate(endpoint_cfg: dict, location: dict, now: float | None = None) -> bool:
    """True if this endpoint's "skip if it hasn't been updated" toggle is on
    and the new fix is (a) not fresh/live and (b) within its configured
    minimum-update-gap of the last fix's own timestamp actually sent - i.e.
    Google is just re-serving the same stale cached report again, not a new
    update. A genuinely live fix (recorded within FRESH_FIX_AGE_S of now)
    always bypasses this and gets sent regardless."""
    if not endpoint_cfg.get("skip_if_stale"):
        return False
    if location.get("is_semantic") or location.get("time") is None:
        return False
    now = time.time() if now is None else now
    if now - location["time"] <= FRESH_FIX_AGE_S:
        return False
    last_fix_time = endpoint_cfg.get("last_sent_fix_time")
    if last_fix_time is None:
        return False  # nothing sent yet for this endpoint - always send the first fix
    gap_s = (endpoint_cfg.get("min_update_gap_m") or DEFAULT_MIN_UPDATE_GAP_M) * 60
    return abs(location["time"] - last_fix_time) < gap_s


def _dispatch_forward(endpoint_cfg: dict, location: dict) -> str:
    """Sends to whichever forwarder type this endpoint is configured for, with
    no distance-skip check - used both by the normal scheduled path (after it
    passes _too_close_to_bother) and by the "send now" button, which is
    meant to bypass that check entirely. Adding a new destination type never
    touches this function - see webui/forwarders/registry.py."""
    ftype = FORWARDER_TYPES.get(endpoint_cfg.get("type"))
    if ftype is None:
        return "skipped"
    try:
        cfg = endpoint_cfg.get(ftype.key) or {}
        ok = ftype.forward(cfg, location)
        return "ok" if ok else "skipped"
    except Exception as e:
        logger.warning("Forwarding failed: %s", e)
        return f"error: {e}"


def _forward_one(endpoint_cfg: dict, location: dict) -> str:
    if _too_close_to_bother(endpoint_cfg, location):
        threshold = endpoint_cfg.get("min_movement_m") or DEFAULT_MIN_MOVEMENT_M
        return f"skipped: moved less than {threshold:g}m"
    if _stale_duplicate(endpoint_cfg, location):
        gap = endpoint_cfg.get("min_update_gap_m") or DEFAULT_MIN_UPDATE_GAP_M
        return f"skipped: not updated in the last {gap:g}m"
    return _dispatch_forward(endpoint_cfg, location)


def _serialize_location(location: dict) -> str:
    """The exact location data a forward attempt worked with, for the
    forwarding log - so a bad reading (or a forwarder silently dropping a
    field) is visible there instead of just the short target summary."""
    try:
        return json.dumps(location, default=str)
    except TypeError:
        return str(location)


def _merge_extra_info(location: dict, extra_info: dict | None) -> dict:
    """Layers live battery/WiFi data (Auth/live_device_info.py) onto a copy
    of location for forwarders that use it (see webui/forwarders/traccar.py,
    phonetrack.py) - never mutates the original, since the same location is
    shared across every due endpoint this cycle and only some of them may
    have "fetch_live_info" on."""
    if not extra_info:
        return location
    merged = dict(location)
    if extra_info.get("battery_pct") is not None:
        merged["battery_pct"] = extra_info["battery_pct"]
    if extra_info.get("wifi_ssid") is not None:
        merged["wifi_ssid"] = extra_info["wifi_ssid"]
    return merged


def _endpoint_target(endpoint_cfg: dict) -> str:
    """Short human-readable destination summary, for the forwarding log."""
    ftype = FORWARDER_TYPES.get(endpoint_cfg.get("type"))
    if ftype is None:
        return ""
    label = ftype.target_label(endpoint_cfg.get(ftype.key) or {})
    alias = endpoint_cfg.get("alias")
    return f"{alias} ({label})" if alias else label


async def _poll_device(canonic_id: str):
    while True:
        device_cfg = config_store.get_device_config(canonic_id)
        endpoints = device_cfg.get("endpoints") if device_cfg else None
        if not endpoints:
            return

        now = datetime.now()
        next_runs = [_next_run(ep.get("cron", DEFAULT_CRON), now) for ep in endpoints]
        valid_next_runs = [t for t in next_runs if t is not None]
        if not valid_next_runs:
            logger.warning("No valid cron schedules for %s; stopping poll loop", canonic_id)
            return

        wake_at = min(valid_next_runs)
        await asyncio.sleep(max(0.0, (wake_at - datetime.now()).total_seconds()))

        due_indices = [i for i, t in enumerate(next_runs) if t is not None and t <= wake_at]

        name = device_cfg.get("display_name", canonic_id)

        wants_live_info = any(endpoints[i].get("fetch_live_info") for i in due_indices)

        if not is_logged_in():
            # Don't trigger the Google login flow from the background poller -
            # that's only ever meant to happen from a deliberate /auth click.
            locations = []
            extra_info = None
        else:
            # The watch has to be open *before* the locate happens - see
            # Auth/live_device_info.py's module docstring - so this comes
            # first, not after locate_device() below.
            watch = await open_live_info_watch(canonic_id) if wants_live_info else None
            try:
                locations = await locate_device(canonic_id, name)
            except Exception as e:
                locations = []
                logger.warning("Locate failed for %s: %s", name, e)
            extra_info = await run_blocking(watch.wait_for_update, 15.0) if watch else None
            if extra_info:
                device_location_store.set_last_extra_info(canonic_id, extra_info, int(time.time()))

        if locations:
            # The Devices page's "last locate result" should reflect cron
            # polls too, not just manual clicks - a timeout/failure above
            # already left `locations` empty, so this never clobbers the
            # last real fix with nothing.
            device_location_store.set_last_location(canonic_id, locations, int(time.time()))

        # Keyed by endpoint index, overwritten on every matching location the
        # same way the old flat status-only version did (last location in the
        # batch wins) - now also carrying which location that status came
        # from, so a successful "ok" can update the endpoint's last-sent
        # position for next time's distance-skip check.
        results: dict[int, dict] = {}
        for location in locations:
            for i in due_indices:
                endpoint_location = location
                if endpoints[i].get("fetch_live_info"):
                    endpoint_location = _merge_extra_info(location, extra_info)
                status = await asyncio.to_thread(_forward_one, endpoints[i], endpoint_location)
                results[i] = {"status": status, "location": location}
                log_store.append(
                    canonic_id=canonic_id,
                    device_name=name,
                    endpoint_type=endpoints[i].get("type", ""),
                    target=_endpoint_target(endpoints[i]),
                    status=status,
                    payload=_serialize_location(endpoint_location),
                )
        for i in due_indices:
            results.setdefault(i, {"status": "no location", "location": None})

        fresh_cfg = config_store.get_device_config(canonic_id) or device_cfg
        fresh_endpoints = fresh_cfg.get("endpoints", [])
        now_ts = int(time.time())
        for i, result in results.items():
            if i >= len(fresh_endpoints):
                continue
            fresh_endpoints[i]["last_forward_status"] = result["status"]
            fresh_endpoints[i]["last_forward_time"] = now_ts
            if result["status"] == "ok" and result["location"] is not None:
                fresh_endpoints[i]["last_sent_lat"] = result["location"]["latitude"]
                fresh_endpoints[i]["last_sent_lon"] = result["location"]["longitude"]
                fresh_endpoints[i]["last_sent_fix_time"] = result["location"].get("time")
        config_store.set_device_config(canonic_id, fresh_cfg)

        if due_indices:
            await ws.manager.broadcast({
                "type": "locate_result",
                "canonic_id": canonic_id,
                "name": name,
                "locations": locations,
                "source": "poll",
            })


async def forward_now(canonic_id: str, index: int) -> dict | None:
    """Immediately forwards one endpoint's current location - the "send now"
    button in the settings UI. Bypasses both its cron schedule and its
    distance-skip threshold (via _dispatch_forward, not _forward_one) since
    forcing a send is the whole point. Returns the endpoint's persisted state
    afterwards, or None if the device/endpoint no longer exists."""
    device_cfg = config_store.get_device_config(canonic_id)
    endpoints = device_cfg.get("endpoints", []) if device_cfg else []
    if not device_cfg or not (0 <= index < len(endpoints)):
        return None

    name = device_cfg.get("display_name", canonic_id)
    endpoint_cfg = endpoints[index]

    wants_live_info = bool(endpoint_cfg.get("fetch_live_info"))
    watch = await open_live_info_watch(canonic_id) if wants_live_info else None
    try:
        locations = await locate_device(canonic_id, name)
    except Exception as e:
        locations = []
        logger.warning("Locate failed for %s: %s", name, e)
    extra_info = await run_blocking(watch.wait_for_update, 15.0) if watch else None
    if extra_info:
        device_location_store.set_last_extra_info(canonic_id, extra_info, int(time.time()))

    status = "no location"
    for location in locations:
        endpoint_location = _merge_extra_info(location, extra_info) if wants_live_info else location
        status = await asyncio.to_thread(_dispatch_forward, endpoint_cfg, endpoint_location)
        log_store.append(
            canonic_id=canonic_id,
            device_name=name,
            endpoint_type=endpoint_cfg.get("type", ""),
            target=_endpoint_target(endpoint_cfg),
            status=status,
            payload=_serialize_location(endpoint_location),
        )
        if status == "ok":
            endpoint_cfg["last_sent_lat"] = location["latitude"]
            endpoint_cfg["last_sent_lon"] = location["longitude"]
            endpoint_cfg["last_sent_fix_time"] = location.get("time")

    endpoint_cfg["last_forward_status"] = status
    endpoint_cfg["last_forward_time"] = int(time.time())
    config_store.set_device_config(canonic_id, device_cfg)
    return endpoint_cfg


def restart_device(canonic_id: str):
    existing = _tasks.pop(canonic_id, None)
    if existing:
        existing.cancel()

    device_cfg = config_store.get_device_config(canonic_id)
    if device_cfg and device_cfg.get("endpoints"):
        _tasks[canonic_id] = asyncio.create_task(_poll_device(canonic_id))


def start_all():
    for canonic_id in config_store.all_devices():
        restart_device(canonic_id)


def stop_all():
    for task in _tasks.values():
        task.cancel()
    _tasks.clear()
