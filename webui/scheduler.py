import asyncio
import logging
import time

from webui import config, ws
from webui.deps import locate_device
from webui.forwarders import config_store
from webui.forwarders.phonetrack import forward_to_phonetrack
from webui.forwarders.traccar import forward_to_traccar

logger = logging.getLogger("webui.scheduler")

_tasks: dict[str, asyncio.Task] = {}


def _forward(device_cfg: dict, location: dict) -> str:
    destination = device_cfg.get("destination", "none")
    try:
        if destination == "traccar":
            traccar_cfg = device_cfg.get("traccar") or {}
            ok = forward_to_traccar(traccar_cfg.get("url", ""), traccar_cfg.get("device_id", ""), location)
        elif destination == "phonetrack":
            pt_cfg = device_cfg.get("phonetrack") or {}
            ok = forward_to_phonetrack(pt_cfg.get("base_url", ""), pt_cfg.get("device_name", ""), location)
        else:
            return "skipped"
        return "ok" if ok else "skipped"
    except Exception as e:
        logger.warning("Forwarding failed: %s", e)
        return f"error: {e}"


async def _poll_device(canonic_id: str):
    while True:
        device_cfg = config_store.get_device_config(canonic_id)
        if device_cfg is None or device_cfg.get("destination", "none") == "none":
            return

        name = device_cfg.get("display_name", canonic_id)
        interval = device_cfg.get("poll_interval_seconds") or config.DEFAULT_POLL_INTERVAL_S

        try:
            locations = await locate_device(canonic_id, name)
        except Exception as e:
            locations = []
            logger.warning("Locate failed for %s: %s", name, e)

        last_status = "no location"
        for location in locations:
            last_status = await asyncio.to_thread(_forward, device_cfg, location)

        device_cfg = config_store.get_device_config(canonic_id) or device_cfg
        device_cfg["last_forward_status"] = last_status
        device_cfg["last_forward_time"] = int(time.time())
        config_store.set_device_config(canonic_id, device_cfg)

        await ws.manager.broadcast({
            "type": "locate_result",
            "canonic_id": canonic_id,
            "name": name,
            "locations": locations,
            "source": "poll",
        })

        await asyncio.sleep(interval)


def restart_device(canonic_id: str):
    existing = _tasks.pop(canonic_id, None)
    if existing:
        existing.cancel()

    device_cfg = config_store.get_device_config(canonic_id)
    if device_cfg and device_cfg.get("destination", "none") != "none":
        _tasks[canonic_id] = asyncio.create_task(_poll_device(canonic_id))


def start_all():
    for canonic_id in config_store.all_devices():
        restart_device(canonic_id)


def stop_all():
    for task in _tasks.values():
        task.cancel()
    _tasks.clear()
