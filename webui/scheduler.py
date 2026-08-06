import asyncio
import logging
import time
from datetime import datetime

from croniter import croniter

from webui import ws
from webui.auth_state import is_logged_in
from webui.deps import locate_device
from webui.forwarders import config_store
from webui.forwarders.phonetrack import forward_to_phonetrack
from webui.forwarders.traccar import forward_to_traccar

logger = logging.getLogger("webui.scheduler")

_tasks: dict[str, asyncio.Task] = {}

DEFAULT_CRON = "*/5 * * * *"


def _next_run(cron_expr: str, base: datetime) -> datetime | None:
    try:
        return croniter(cron_expr, base).get_next(datetime)
    except Exception as e:
        logger.warning("Invalid cron expression %r: %s", cron_expr, e)
        return None


def _forward_one(endpoint_cfg: dict, location: dict) -> str:
    etype = endpoint_cfg.get("type")
    try:
        if etype == "traccar":
            t_cfg = endpoint_cfg.get("traccar") or {}
            ok = forward_to_traccar(t_cfg.get("url", ""), t_cfg.get("device_id", ""), location)
        elif etype == "phonetrack":
            p_cfg = endpoint_cfg.get("phonetrack") or {}
            ok = forward_to_phonetrack(p_cfg.get("base_url", ""), p_cfg.get("device_name", ""), location)
        else:
            return "skipped"
        return "ok" if ok else "skipped"
    except Exception as e:
        logger.warning("Forwarding failed: %s", e)
        return f"error: {e}"


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

        statuses = {}
        for location in locations:
            for i in due_indices:
                statuses[i] = await asyncio.to_thread(_forward_one, endpoints[i], location)
        for i in due_indices:
            statuses.setdefault(i, "no location")

        fresh_cfg = config_store.get_device_config(canonic_id) or device_cfg
        fresh_endpoints = fresh_cfg.get("endpoints", [])
        now_ts = int(time.time())
        for i, status in statuses.items():
            if i < len(fresh_endpoints):
                fresh_endpoints[i]["last_forward_status"] = status
                fresh_endpoints[i]["last_forward_time"] = now_ts
        config_store.set_device_config(canonic_id, fresh_cfg)

        if due_indices:
            await ws.manager.broadcast({
                "type": "locate_result",
                "canonic_id": canonic_id,
                "name": name,
                "locations": locations,
                "source": "poll",
            })


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
