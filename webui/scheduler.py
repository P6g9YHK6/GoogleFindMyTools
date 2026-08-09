import asyncio
import logging
import time
from datetime import datetime

from croniter import croniter

from webui import device_location_store, ws
from webui.auth_state import is_logged_in
from webui.deps import locate_device
from webui.forwarders import config_store, log_store
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


def _next_run(cron_expr: str, base: datetime) -> datetime | None:
    try:
        return croniter(cron_expr, base).get_next(datetime)
    except Exception as e:
        logger.warning("Invalid cron expression %r: %s", cron_expr, e)
        return None


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
                status = await asyncio.to_thread(_forward_one, endpoints[i], endpoint_location, name)
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
            _record_forward_result(fresh_endpoints[i], result["status"], result["location"], name, now_ts)
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

    try:
        locations = await locate_device(canonic_id, name)
    except Exception as e:
        locations = []
        logger.warning("Locate failed for %s: %s", name, e)

    status = "no location"
    for location in locations:
        endpoint_location = location
        status = await asyncio.to_thread(_dispatch_forward, endpoint_cfg, endpoint_location, name)
        log_store.append(
            canonic_id=canonic_id,
            device_name=name,
            endpoint_type=endpoint_cfg.get("type", ""),
            target=_endpoint_target(endpoint_cfg),
            status=status,
            payload=_serialize_location(endpoint_location),
        )
        _record_forward_result(endpoint_cfg, status, endpoint_location, name)

    if not locations:
        # Nothing to record per-location above - still needs its
        # last_forward_status/time updated to reflect this attempt.
        _record_forward_result(endpoint_cfg, status, None, name)

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
