"""Forwarding policy: the skip-if-close/skip-if-stale gates, the generic
dispatch-and-log call every endpoint goes through, and the "did this
destination just start failing" escalation. Deliberately decoupled from
*when* any of this runs - that's webui/scheduler.py's job, the cron loop
built on top of everything here.
"""

import json
import logging
import time

from webui.forwarders.custom import forward_to_custom
from webui.geo import haversine_distance_m

logger = logging.getLogger("webui.forwarders.policy")

DEFAULT_MIN_MOVEMENT_M = 50
DEFAULT_MIN_UPDATE_GAP_M = 30
# A fix this recent is treated as a genuinely live update rather than Google
# re-serving the same stale cached report - always sent regardless of the
# stale-duplicate gate below.
FRESH_FIX_AGE_S = 120
# After this many consecutive failed attempts, escalate a destination's
# ongoing failures via logger.error (picked up by the System Log and, if
# configured, Apprise - see webui/notify.py) rather than leaving it visible
# only to whoever happens to check the Forwarding Log. Repeats every further
# multiple of this instead of once, so a destination that's been down for
# days still gets an occasional reminder instead of one message that scrolls
# off and is never mentioned again.
FORWARD_FAILURE_ESCALATION_THRESHOLD = 3


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


def _dispatch_forward(
    endpoint_cfg: dict, location: dict, device_name: str = "", device_alias: str | None = None,
) -> str:
    """Sends this endpoint's request, with no distance-skip check - used both
    by the normal scheduled path (after it passes _too_close_to_bother) and
    by the "send now" button, which is meant to bypass that check entirely.
    Every endpoint goes through the same generic templated request (see
    webui/forwarders/custom.py); Traccar/PhoneTrack are presets that pre-fill
    it, not separate code paths - see webui/forwarders/presets.py."""
    try:
        ok = forward_to_custom(endpoint_cfg, location, device_name, device_alias)
        return "ok" if ok else "skipped"
    except Exception as e:
        logger.warning("Forwarding failed: %s", e)
        return f"error: {e}"


def _forward_one(
    endpoint_cfg: dict, location: dict, device_name: str = "", device_alias: str | None = None,
) -> str:
    if _too_close_to_bother(endpoint_cfg, location):
        threshold = endpoint_cfg.get("min_movement_m") or DEFAULT_MIN_MOVEMENT_M
        return f"skipped: moved less than {threshold:g}m"
    if _stale_duplicate(endpoint_cfg, location):
        gap = endpoint_cfg.get("min_update_gap_m") or DEFAULT_MIN_UPDATE_GAP_M
        return f"skipped: not updated in the last {gap:g}m"
    return _dispatch_forward(endpoint_cfg, location, device_name, device_alias)


def _serialize_location(location: dict) -> str:
    """The exact location data a forward attempt worked with, for the
    forwarding log - so a bad reading (or a forwarder silently dropping a
    field) is visible there instead of just the short target summary."""
    try:
        return json.dumps(location, default=str)
    except TypeError:
        return str(location)


def _endpoint_target(endpoint_cfg: dict) -> str:
    """Short human-readable destination summary, for the forwarding log."""
    url = endpoint_cfg.get("url") or ""
    method = endpoint_cfg.get("method") or "GET"
    label = f"{method} {url}".strip()
    alias = endpoint_cfg.get("alias")
    return f"{alias} ({label})" if alias else label


def _record_forward_result(
    endpoint_cfg: dict, status: str, location: dict | None, device_display_name: str, now_ts: int | None = None,
):
    """Updates one endpoint's persisted last-forward state after a single
    attempt (used by both the cron poll loop and "send now"), and escalates
    via logger.error once it's crossed FORWARD_FAILURE_ESCALATION_THRESHOLD
    consecutive failures - see that constant's comment. A "skipped" status
    (the distance/staleness gates, or simply nothing to send) is neither
    success nor failure, so it's left out of the streak entirely rather than
    resetting or extending it."""
    endpoint_cfg["last_forward_status"] = status
    endpoint_cfg["last_forward_time"] = now_ts if now_ts is not None else int(time.time())

    if status == "ok" and location is not None:
        endpoint_cfg["last_sent_lat"] = location["latitude"]
        endpoint_cfg["last_sent_lon"] = location["longitude"]
        endpoint_cfg["last_sent_fix_time"] = location.get("time")
        endpoint_cfg["consecutive_failures"] = 0
    elif status.startswith("error"):
        failures = endpoint_cfg.get("consecutive_failures", 0) + 1
        endpoint_cfg["consecutive_failures"] = failures
        if failures % FORWARD_FAILURE_ESCALATION_THRESHOLD == 0:
            logger.error(
                "Forwarding to %s for %s has failed %d times in a row (latest: %s)",
                _endpoint_target(endpoint_cfg), device_display_name, failures, status,
            )
