"""The last location actually obtained for each device - written from both
places that call locate_device() (webui/routers/locate.py's manual button
and webui/scheduler.py's cron polling), so the Devices page can always show
something instead of going blank on every page load until someone clicks
Locate again. Same small-persisted-YAML shape as webui/settings_store.py;
there's nothing to migrate from, so no legacy-JSON fallback here.
"""

import threading

import yaml

from webui import config

_lock = threading.Lock()


def _load_unlocked() -> dict:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not config.DEVICE_LOCATIONS_PATH.exists():
        return {}
    try:
        with open(config.DEVICE_LOCATIONS_PATH) as f:
            data = yaml.safe_load(f)
    except (yaml.YAMLError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_unlocked(data: dict):
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(config.DEVICE_LOCATIONS_PATH, "w") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)


def get_last_location(canonic_id: str) -> dict | None:
    """{"locations": [...], "fetched_at": <unix ts>}, or None if nothing's
    ever been obtained for this device."""
    with _lock:
        return _load_unlocked().get(canonic_id)


def set_last_location(canonic_id: str, locations: list[dict], fetched_at: int):
    """Only ever call this with a non-empty `locations` - a timeout/failure
    must never clobber the last real result callers already have on file."""
    with _lock:
        data = _load_unlocked()
        data[canonic_id] = {"locations": locations, "fetched_at": fetched_at}
        _save_unlocked(data)
