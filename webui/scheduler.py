import asyncio
import logging
import time
from datetime import datetime

from croniter import croniter

from webui import device_location_store, settings_store, ws
from webui.auth_state import is_logged_in
from webui.deps import locate_device
from webui.forwarders import config_store, latest_values_store, log_store
from webui.forwarders.policy import (
    _dispatch_forward,
    _endpoint_target,
    _forward_one,
    _record_forward_result,
    _serialize_location,
)

logger = logging.getLogger("webui.scheduler")

_tasks: dict[str, asyncio.Task] = {}

DEFAULT_CRON = "*/5 * * * *"

# Friendly names for the schedule editor's preset dropdown - the common cases
# most people actually want, so they never have to think about cron syntax
# at all. Anything else falls back to the "Custom" advanced builder below it
# (see webui/routers/settings.py's cron_presets/cron_preset_values, and
# webui/templates/settings/_endpoint_fields.html).
CRON_PRESETS = [
    ("Every minute", "* * * * *"),
    ("Every 5 minutes", "*/5 * * * *"),
    ("Every 15 minutes", "*/15 * * * *"),
    ("Every 30 minutes", "*/30 * * * *"),
    ("Every hour", "0 * * * *"),
    ("Every 2 hours", "0 */2 * * *"),
    ("Every 6 hours", "0 */6 * * *"),
    ("Once a day", "0 0 * * *"),
]


def _next_run(cron_expr: str, base: datetime) -> datetime | None:
    try:
        return croniter(cron_expr, base).get_next(datetime)
    except Exception as e:
        logger.warning("Invalid cron expression %r: %s", cron_expr, e)
        return None


def cron_preview(cron_expr: str, count: int = 3, base: datetime | None = None) -> dict:
    """Human-facing preview for the schedule editor: either the next `count`
    occurrences of cron_expr, pre-formatted (same convention as
    webui/routers/devices.py's other timestamp strings), or a validity
    flag - used both for the initial page render (as a Jinja global, see
    webui/templating.py) and by the live htmx preview in
    webui/routers/settings.py, so there's exactly one place that decides
    what "next run" means, and it can never disagree with the real poll
    loop above (which uses the same croniter call)."""
    cron_expr = (cron_expr or "").strip()
    if not cron_expr or not croniter.is_valid(cron_expr):
        return {"valid": False}
    it = croniter(cron_expr, base or datetime.now())
    runs = [it.get_next(datetime) for _ in range(count)]
    return {"valid": True, "runs_str": [r.strftime("%Y-%m-%d %H:%M") for r in runs]}


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

        # name is the local, editable alias (see webui/routers/settings.py's
        # _rows) - falls back to canonic_id if this device was never
        # actually saved through the settings UI. Used everywhere below that
        # just needs one human-friendly label (locate logging, the
        # forwarding log, the websocket broadcast) exactly as before
        # device_alias existed as its own template token. google_name is the
        # real, fixed name from the Google account itself, kept in sync
        # locally by that same _rows() on every settings-page load so it's
        # available here without a live device-list fetch on every poll -
        # falls back to the alias (then canonic_id) for a device saved
        # before google_name started being persisted. {{device_name}} and
        # {{device_alias}} in a template resolve to google_name and name
        # respectively - see webui/forwarders/custom.py's build_context.
        name = device_cfg.get("display_name", canonic_id)
        google_name = device_cfg.get("google_name") or name

        if not is_logged_in():
            # Don't trigger the Google login flow from the background poller -
            # that's only ever meant to happen from a deliberate /auth click.
            locations = []
        else:
            try:
                locations = await locate_device(canonic_id, name)
            except Exception as e:
                locations = []
                logger.warning("Locate failed for %s: %s", name, e)

        already_seen_by_index: list[bool] = []
        is_most_recent_by_index: list[bool] = []
        if locations:
            # The Devices page's "last locate result" should reflect cron
            # polls too, not just manual clicks - a timeout/failure above
            # already left `locations` empty, so this never clobbers the
            # last real fix with nothing. Reassigned to the stamped list
            # set_last_location returns, whose transient "_new_this_fetch"
            # is how the forwarding loop below tells a genuinely new reading
            # apart from Google re-serving one it already returned before -
            # captured into a plain parallel list and popped off each dict
            # right away, so it never leaks into the websocket broadcast or
            # the forwarding payload below.
            locations = device_location_store.set_last_location(canonic_id, locations, int(time.time()))
            already_seen_by_index = [not loc.pop("_new_this_fetch") for loc in locations]
            # Google can bundle several readings in one response (see
            # decrypt_locations.py) in no particular order - computed once
            # per batch here, same "skip" role as already_seen_by_index
            # above, for policy._skip_not_most_recent's per-endpoint toggle.
            most_recent_time = max(
                (loc.get("time") for loc in locations if loc.get("time") is not None), default=None,
            )
            is_most_recent_by_index = [
                most_recent_time is None or loc.get("time") == most_recent_time for loc in locations
            ]

        # Keyed by endpoint index, overwritten on every matching location the
        # same way the old flat status-only version did (last location in the
        # batch wins) - now also carrying which location that status came
        # from, so a successful "ok" can update the endpoint's last-sent
        # position for next time's distance-skip check. Each result also
        # captures the URL its request actually went to and a merged
        # config+state view (see latest_values_store) up front, rather than
        # re-reading `endpoints` after the fact below - a concurrent
        # settings save could otherwise change what's at that position
        # mid-poll.
        results: dict[int, dict] = {}
        for location, already_seen, is_most_recent in zip(locations, already_seen_by_index, is_most_recent_by_index):
            for i in due_indices:
                url = endpoints[i].get("url", "")
                merged = {**endpoints[i], **latest_values_store.get_endpoint_state(canonic_id, url)}
                status = await asyncio.to_thread(
                    _forward_one, merged, location, google_name, name, already_seen, is_most_recent,
                )
                results[i] = {"status": status, "location": location, "url": url, "merged": merged}
                log_store.append(
                    canonic_id=canonic_id,
                    device_name=name,
                    endpoint_type=endpoints[i].get("type", ""),
                    target=_endpoint_target(endpoints[i]),
                    status=status,
                    payload=_serialize_location(location),
                )
        for i in due_indices:
            if i not in results:
                url = endpoints[i].get("url", "")
                merged = {**endpoints[i], **latest_values_store.get_endpoint_state(canonic_id, url)}
                results[i] = {"status": "no location", "location": None, "url": url, "merged": merged}

        now_ts = int(time.time())
        for result in results.values():
            _record_forward_result(result["merged"], result["status"], result["location"], name, now_ts)
            state = {k: result["merged"][k] for k in latest_values_store.STATE_KEYS if k in result["merged"]}
            latest_values_store.set_endpoint_state(canonic_id, result["url"], state)

        if due_indices:
            # Display-only, same as webui/routers/locate.py's manual button -
            # forwarding above already saw the full `locations`; this is just
            # what's broadcast to live map pins on the Devices page, so a
            # cron poll's live update never disagrees with what a page
            # reload (webui/routers/devices.py) would show.
            display_locations = locations
            if display_locations and settings_store.load().get("devices_page_most_recent_only"):
                display_locations = device_location_store.most_recent_only(display_locations)
            await ws.manager.broadcast({
                "type": "locate_result",
                "canonic_id": canonic_id,
                "name": name,
                "locations": display_locations,
                "source": "poll",
            })


async def forward_now(canonic_id: str, index: int) -> dict | None:
    """Immediately forwards one endpoint's current location - the "send now"
    button in the settings UI. Bypasses both its cron schedule and its
    distance-skip threshold (via _dispatch_forward, not _forward_one) since
    forcing a send is the whole point. Returns the endpoint's config merged
    with its freshly-recorded state (see latest_values_store) - the same
    shape _endpoint_fields.html expects to render - or None if the
    device/endpoint no longer exists."""
    device_cfg = config_store.get_device_config(canonic_id)
    endpoints = device_cfg.get("endpoints", []) if device_cfg else []
    if not device_cfg or not (0 <= index < len(endpoints)):
        return None

    # See the matching comment in _poll_device above - name is the local
    # alias, google_name the account's real (fixed) name.
    name = device_cfg.get("display_name", canonic_id)
    google_name = device_cfg.get("google_name") or name
    endpoint_cfg = endpoints[index]
    url = endpoint_cfg.get("url", "")
    merged = {**endpoint_cfg, **latest_values_store.get_endpoint_state(canonic_id, url)}

    try:
        locations = await locate_device(canonic_id, name)
    except Exception as e:
        locations = []
        logger.warning("Locate failed for %s: %s", name, e)

    status = "no location"
    for location in locations:
        endpoint_location = location
        status = await asyncio.to_thread(_dispatch_forward, endpoint_cfg, endpoint_location, google_name, name)
        log_store.append(
            canonic_id=canonic_id,
            device_name=name,
            endpoint_type=endpoint_cfg.get("type", ""),
            target=_endpoint_target(endpoint_cfg),
            status=status,
            payload=_serialize_location(endpoint_location),
        )
        _record_forward_result(merged, status, endpoint_location, name)

    if not locations:
        # Nothing to record per-location above - still needs its
        # last_forward_status/time updated to reflect this attempt.
        _record_forward_result(merged, status, None, name)

    state = {k: merged[k] for k in latest_values_store.STATE_KEYS if k in merged}
    latest_values_store.set_endpoint_state(canonic_id, url, state)
    return merged


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
