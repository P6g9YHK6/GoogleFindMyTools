import json
import threading

from webui import config

_lock = threading.Lock()


def _empty():
    return {"devices": {}}


def _seconds_to_cron(seconds) -> str:
    # Best-effort translation of a legacy poll_interval_seconds value into an
    # equivalent cron expression, for devices saved before endpoints existed.
    seconds = seconds or config.DEFAULT_POLL_INTERVAL_S
    minutes = max(1, round(seconds / 60))
    if minutes <= 59:
        return f"*/{minutes} * * * *"
    hours = min(23, max(1, round(minutes / 60)))
    return f"0 */{hours} * * *"


def normalize_device_config(device_cfg: dict) -> dict:
    """Convert a pre-multi-endpoint device record into the current endpoints-list
    shape. A no-op on records that already have "endpoints"."""
    if "endpoints" in device_cfg:
        return device_cfg

    normalized = dict(device_cfg)
    destination = normalized.pop("destination", "none")
    old_traccar = normalized.pop("traccar", None)
    old_phonetrack = normalized.pop("phonetrack", None)
    last_status = normalized.pop("last_forward_status", None)
    last_time = normalized.pop("last_forward_time", None)
    poll_interval = normalized.pop("poll_interval_seconds", None)
    cron_expr = _seconds_to_cron(poll_interval)

    endpoints = []
    if destination == "traccar" and old_traccar:
        endpoints.append({
            "type": "traccar", "traccar": old_traccar, "cron": cron_expr,
            "last_forward_status": last_status, "last_forward_time": last_time,
        })
    elif destination == "phonetrack" and old_phonetrack:
        endpoints.append({
            "type": "phonetrack", "phonetrack": old_phonetrack, "cron": cron_expr,
            "last_forward_status": last_status, "last_forward_time": last_time,
        })
    # destination == "none" (or missing) -> empty list, forwarding stays disabled

    normalized["endpoints"] = endpoints
    return normalized


def load() -> dict:
    with _lock:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        if not config.FORWARDING_CONFIG_PATH.exists():
            return _empty()
        try:
            with open(config.FORWARDING_CONFIG_PATH) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return _empty()
        data.setdefault("devices", {})
        return data


def save(data: dict):
    with _lock:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(config.FORWARDING_CONFIG_PATH, "w") as f:
            json.dump(data, f, indent=2)


def get_device_config(canonic_id: str) -> dict | None:
    device_cfg = load()["devices"].get(canonic_id)
    return normalize_device_config(device_cfg) if device_cfg is not None else None


def set_device_config(canonic_id: str, device_config: dict):
    data = load()
    data["devices"][canonic_id] = device_config
    save(data)


def all_devices() -> dict:
    return {
        canonic_id: normalize_device_config(device_cfg)
        for canonic_id, device_cfg in load()["devices"].items()
    }
