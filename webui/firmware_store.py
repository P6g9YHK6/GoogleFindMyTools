"""Advertisement keys (EIDs) produced by /register, kept around so the
Firmware page (webui/routers/firmware.py) can offer a previously-registered
tracker again instead of requiring the user to copy-paste the one-time value
shown right after registering. Same small-persisted-YAML shape as
webui/device_location_store.py/webui/settings_store.py.

Only the public EID and its pairing date are stored - never the private eik
(see SpotApi/CreateBleDevice/create_ble_device.py, which never returns eik
to the webui at all), so this is no more sensitive than the value the
firmware itself broadcasts openly over BLE.
"""

import threading

import yaml

from webui import config

_lock = threading.Lock()

# Keep the file from growing forever across many /register clicks - the
# Firmware page only ever needs recent ones to pick from.
_MAX_ENTRIES = 50


def _load_unlocked() -> list[dict]:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not config.REGISTERED_TRACKERS_PATH.exists():
        return []
    try:
        with open(config.REGISTERED_TRACKERS_PATH) as f:
            data = yaml.safe_load(f)
    except (yaml.YAMLError, OSError):
        return []
    return data if isinstance(data, list) else []


def _save_unlocked(entries: list[dict]):
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(config.REGISTERED_TRACKERS_PATH, "w") as f:
        yaml.safe_dump(entries, f, sort_keys=False, allow_unicode=True)


def record_registration(eid_hex: str, pair_date: int):
    with _lock:
        entries = _load_unlocked()
        entries.insert(0, {"eid_hex": eid_hex, "pair_date": pair_date})
        _save_unlocked(entries[:_MAX_ENTRIES])


def list_registered() -> list[dict]:
    with _lock:
        return _load_unlocked()
