"""Per-device staleness alerting (issue #22): "this device hasn't produced a
newer location fix in longer than expected", used as a proxy for a dead
battery or a BLE tag that's drifted out of range of any nearby phone.

Deliberately time-only, no movement/distance check and no new history of its
own - just a live comparison between now and the newest "time" already on
file for this device (see webui/device_location_store.py), the same signal
the Devices page itself shows. Config + the small bit of alert-dedup
bookkeeping needed to avoid re-notifying every sweep live in
webui/forwarders/latest_values_store.py (get_device_staleness/
set_device_staleness), not here and not in forwarding.yaml - see that
module's own comment for why.

Distinct concern from webui/scheduler.py (owns *when* a device gets polled)
and webui/forwarders/policy.py (owns *whether a fix is worth forwarding*) -
this owns neither; it just asks "is the newest fix we have too old", on its
own independent sweep, since a device with no forwarding endpoints
configured is never polled by scheduler.py's per-device cron loop at all.
"""

import asyncio
import logging
import re
import time

from webui import device_location_store, settings_store
from webui.forwarders import config_store, latest_values_store

logger = logging.getLogger("webui.staleness")

_TOKEN_RE = re.compile(r"\{\{(\w+)\}\}")

DEFAULT_MESSAGE_TEMPLATE = "No update from {{device_name}} in over {{threshold}}"


def render_template(template: str, ctx: dict) -> str:
    """Same {{name}} substitution convention as forwarding endpoints (see
    webui/forwarders/custom.py's own _render) - not shared code with that
    module since it's private there and this alert message template has a
    much smaller, fixed vocabulary (see _alert_context below), not
    per-endpoint custom variables. An unresolved token (a typo) is left in
    place rather than dropped, same reasoning as custom.py's own version:
    obvious in the actual notification instead of silently sending less
    than intended."""
    if not template:
        return ""
    return _TOKEN_RE.sub(lambda m: str(ctx.get(m.group(1), m.group(0))), template)

# Friendly duration choices for the threshold/repeat selects - same "preset
# dropdown + custom fallback" shape as webui/scheduler.py's CRON_PRESETS,
# just for a plain duration instead of a cron expression. Both the threshold
# and the repeat-cadence field reuse this same list (see the Staleness page
# template) - the user asked for one consistent control, not two different
# vocabularies.
DURATION_PRESETS: list[tuple[str, int]] = [
    ("6 hours", 6 * 3600),
    ("12 hours", 12 * 3600),
    ("24 hours", 24 * 3600),
    ("2 days", 2 * 24 * 3600),
    ("3 days", 3 * 24 * 3600),
    ("1 week", 7 * 24 * 3600),
]
DURATION_PRESET_VALUES = {value for _, value in DURATION_PRESETS}

# Sentinel posted by the repeat-cadence select's "Off" option (never a real
# duration value) - "alert once when it goes stale, then stay silent until
# it recovers" rather than nagging on every sweep.
REPEAT_OFF = "off"


def default_staleness() -> dict:
    return {
        "enabled": False,
        "threshold_s": None,
        "repeat_s": None,
        "message_template": DEFAULT_MESSAGE_TEMPLATE,
        "muted": False,
        "alert_active": False,
        "last_alert_sent_at": None,
    }


def _format_duration(seconds: float | int | None) -> str:
    """"2 days"/"18 hours"/"45 minutes" - coarse on purpose, this is for a
    notification message and a table cell, not a precise log timestamp."""
    if seconds is None:
        return "?"
    seconds = int(seconds)
    if seconds < 3600:
        minutes = max(1, seconds // 60)
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    if seconds < 86400:
        hours = seconds // 3600
        return f"{hours} hour{'s' if hours != 1 else ''}"
    days = seconds // 86400
    return f"{days} day{'s' if days != 1 else ''}"


def _newest_fix_time(canonic_id: str) -> int | None:
    """The freshest "time" (the fix's own timestamp, not when we happened to
    fetch it - see device_location_store.py's first_seen for that other,
    deliberately-not-used-here signal) across whatever's on file for this
    device, or None if nothing's ever been located."""
    last = device_location_store.get_last_location(canonic_id)
    if not last or not last.get("locations"):
        return None
    times = [loc.get("time") for loc in last["locations"] if not loc.get("is_semantic") and loc.get("time")]
    return max(times) if times else None


def compute_status(canonic_id: str, staleness_cfg: dict, now: float | None = None) -> dict:
    """Pure function: this device's current staleness status, given its
    config (see latest_values_store.get_device_staleness) - used by both the
    sweep below and the Staleness page's own render, so the two can never
    disagree about what "stale" means."""
    now = time.time() if now is None else now
    enabled = bool(staleness_cfg.get("enabled"))
    muted = bool(staleness_cfg.get("muted"))
    threshold_s = staleness_cfg.get("threshold_s")
    last_fix_time = _newest_fix_time(canonic_id)
    has_data = last_fix_time is not None
    age_s = (now - last_fix_time) if last_fix_time is not None else None
    is_stale = bool(enabled and threshold_s and age_s is not None and age_s > threshold_s)
    return {
        "enabled": enabled,
        "muted": muted,
        "threshold_s": threshold_s,
        "last_fix_time": last_fix_time,
        "age_s": age_s,
        "has_data": has_data,
        "is_stale": is_stale,
    }


def _alert_context(canonic_id: str, name: str, alias: str, status: dict) -> dict:
    return {
        "device_name": name or "",
        "device_alias": alias or name or "",
        "tracker_id": canonic_id,
        "threshold": _format_duration(status["threshold_s"]),
        "age": _format_duration(status["age_s"]),
    }


def sweep_once(now: float | None = None):
    """One pass over every device: fires (or repeats/clears) a staleness
    alert for each enabled, unmuted device whose threshold has been crossed.
    Called on a timer by sweep_loop below, and directly by tests."""
    now = time.time() if now is None else now
    devices = config_store.all_devices()
    for canonic_id, device_cfg in devices.items():
        staleness_cfg = latest_values_store.get_device_staleness(canonic_id)
        if not staleness_cfg or not staleness_cfg.get("enabled") or staleness_cfg.get("muted"):
            continue

        name = device_cfg.get("google_name") or device_cfg.get("display_name") or canonic_id
        alias = device_cfg.get("display_name") or name
        status = compute_status(canonic_id, staleness_cfg, now=now)
        alert_active = bool(staleness_cfg.get("alert_active"))
        changed = False

        if status["is_stale"]:
            repeat_s = staleness_cfg.get("repeat_s")
            last_sent = staleness_cfg.get("last_alert_sent_at")
            should_fire = not alert_active or (repeat_s and (last_sent is None or now - last_sent >= repeat_s))
            if should_fire:
                template = staleness_cfg.get("message_template") or DEFAULT_MESSAGE_TEMPLATE
                message = render_template(template, _alert_context(canonic_id, name, alias, status))
                logger.warning("%s", message)
                staleness_cfg["alert_active"] = True
                staleness_cfg["last_alert_sent_at"] = now
                changed = True
        elif alert_active:
            logger.warning("%s is reporting again (was stale for over %s)", alias, _format_duration(status["threshold_s"]))
            staleness_cfg["alert_active"] = False
            staleness_cfg["last_alert_sent_at"] = None
            changed = True

        if changed:
            latest_values_store.set_device_staleness(canonic_id, staleness_cfg)


async def sweep_loop():
    """Runs sweep_once() on a timer, independent of any device's own cron
    schedule - a device with zero forwarding endpoints is never polled by
    webui/scheduler.py's per-device loops at all, so staleness can't
    piggyback on those. Interval is re-read from settings_store on every
    iteration (see webui/settings_store.py's staleness_sweep_interval_s),
    same live-without-restart convention as the query throttle. Started from
    webui/main.py's lifespan alongside scheduler.start_all()."""
    while True:
        try:
            sweep_once()
        except Exception:
            logger.exception("Staleness sweep failed")
        interval = settings_store.load().get("staleness_sweep_interval_s") or 3600
        await asyncio.sleep(max(60, interval))
