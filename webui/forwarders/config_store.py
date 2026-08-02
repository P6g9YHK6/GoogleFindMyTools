import json
import threading

from webui import config

_lock = threading.Lock()


def _empty():
    return {"devices": {}}


def load() -> dict:
    with _lock:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        if not config.FORWARDING_CONFIG_PATH.exists():
            return _empty()
        try:
            with open(config.FORWARDING_CONFIG_PATH, "r") as f:
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
    return load()["devices"].get(canonic_id)


def set_device_config(canonic_id: str, device_config: dict):
    data = load()
    data["devices"][canonic_id] = device_config
    save(data)


def all_devices() -> dict:
    return load()["devices"]
