"""Single on-disk file (devices.yaml) backing config_store.py,
device_location_store.py and latest_values_store.py. These used to be three
separate YAML files, all keyed by the same canonic device ID - genuinely
redundant, since every real operation is already scoped to one device. Now
one file, one lock, one shape:

{"schema_version": 1, "devices": {<canonic_id>: {
    "config": {...},          # config_store.py: display_name, endpoints
    "location": {...},        # device_location_store.py: locations, fetched_at
    "endpoint_state": {...},  # latest_values_store.py: keyed by endpoint URL
    "staleness": {...},       # latest_values_store.py
}}}

Each of the three modules above still owns its own sub-key and public API;
this module only owns the shared file, lock, and one-time migration from the
three pre-fusion files.
"""

import copy
import json
import threading
from collections.abc import Callable

from webui import config
from webui.yaml_io import read_yaml_dict, write_yaml_dict

_lock = threading.Lock()
_SCHEMA_VERSION = 1
_last_load_ok = True


def last_load_ok() -> bool:
    return _last_load_ok


def _empty() -> dict:
    return {"schema_version": _SCHEMA_VERSION, "devices": {}}


def _migrate_legacy_forwarding() -> dict:
    data, _ok = read_yaml_dict(config.FORWARDING_CONFIG_PATH)
    if not data and config.FORWARDING_CONFIG_LEGACY_JSON_PATH.exists():
        try:
            with open(config.FORWARDING_CONFIG_LEGACY_JSON_PATH) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            data = {}
    devices = data.get("devices") if isinstance(data, dict) else None
    return devices if isinstance(devices, dict) else {}


def _migrate_legacy_files() -> dict | None:
    """One-time fold-in of the pre-fusion forwarding.yaml (or its own
    pre-YAML forwarding_config.json)/device_locations.yaml/latest_values.yaml
    into devices.yaml. Only runs when devices.yaml doesn't exist yet; every
    read after that hits it directly. Returns None (caller falls back to
    _empty()) if none of the legacy files exist either - a genuinely fresh
    install."""
    if not any(p.exists() for p in (
        config.FORWARDING_CONFIG_PATH, config.FORWARDING_CONFIG_LEGACY_JSON_PATH,
        config.DEVICE_LOCATIONS_PATH, config.LATEST_VALUES_PATH,
    )):
        return None

    forwarding = _migrate_legacy_forwarding()
    locations, _ok = read_yaml_dict(config.DEVICE_LOCATIONS_PATH)
    latest_values, _ok = read_yaml_dict(config.LATEST_VALUES_PATH)

    devices = {}
    for canonic_id in set(forwarding) | set(locations) | set(latest_values):
        entry = {}
        if canonic_id in forwarding:
            entry["config"] = forwarding[canonic_id]
        loc = locations.get(canonic_id) or {}
        if "locations" in loc:
            entry["location"] = {"locations": loc["locations"], "fetched_at": loc.get("fetched_at")}
        lv = dict(latest_values.get(canonic_id) or {})
        staleness = lv.pop("__staleness__", None)
        if lv:
            entry["endpoint_state"] = lv
        if staleness:
            entry["staleness"] = staleness
        devices[canonic_id] = entry

    data = {"schema_version": _SCHEMA_VERSION, "devices": devices}
    _save_unlocked(data)
    return data


def _load_unlocked() -> dict:
    global _last_load_ok
    if not config.DEVICES_PATH.exists():
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        _last_load_ok = True
        return _migrate_legacy_files() or _empty()
    data, ok = read_yaml_dict(config.DEVICES_PATH)
    _last_load_ok = ok
    if not ok:
        return _empty()
    data.setdefault("devices", {})
    data.setdefault("schema_version", _SCHEMA_VERSION)
    return data


def _save_unlocked(data: dict):
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    write_yaml_dict(config.DEVICES_PATH, data)


def load() -> dict:
    with _lock:
        return _load_unlocked()


def save(data: dict):
    with _lock:
        _save_unlocked(data)


def mutate_device(canonic_id: str, fn: Callable[[dict], None]) -> dict:
    """Read-modify-write a single device's entry under one lock. fn mutates
    the entry (a fresh copy, safe to modify in place) - only persists if fn
    actually changed something, and drops the entry entirely if fn leaves it
    empty. Returns the entry after fn runs."""
    with _lock:
        data = _load_unlocked()
        devices = data.setdefault("devices", {})
        before = devices.get(canonic_id)
        entry = copy.deepcopy(before) if before is not None else {}
        fn(entry)
        if entry != (before or {}):
            if entry:
                devices[canonic_id] = entry
            else:
                devices.pop(canonic_id, None)
            _save_unlocked(data)
        return entry
