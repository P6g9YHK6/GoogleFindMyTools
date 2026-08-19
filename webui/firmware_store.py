"""Advertisement keys (EIDs) produced by /register, kept around so the
Firmware page (webui/routers/firmware.py) can offer a previously-registered
tracker again instead of requiring the user to copy-paste the one-time value
shown right after registering. Same small-persisted-YAML shape as
webui/device_location_store.py/webui/settings_store.py.

Also remembers the Advanced-section build values (device name, advertising
interval, TX power, unwanted-tracking-protection flag - see
webui/firmware_build.py) last used for each EID, so picking a known EID again
on the Firmware page pre-fills the same settings instead of resetting to
defaults.

Only the public EID and these build settings are stored - never the private
eik (see SpotApi/CreateBleDevice/create_ble_device.py, which never returns
eik to the webui at all), so this is no more sensitive than the values the
firmware itself broadcasts openly over BLE.
"""

import threading

import yaml

from webui import config

_lock = threading.Lock()

# Keep the file from growing forever across many /register clicks - the
# Firmware page only ever needs recent ones to pick from.
_MAX_ENTRIES = 50

# What a build looks like before its EID's Advanced section has ever been
# touched - matches ESP32Firmware/main/build_config.h's checked-in defaults
# exactly, so an old entry that predates this feature still builds identically
# to before.
DEFAULT_BUILD_SETTINGS = {
    "device_name": "GFMT Tracker",
    "adv_interval_ms": 20,
    "tx_power_dbm": 9,
    "tracking_protection": True,
}


def _load_unlocked() -> list[dict]:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not config.REGISTERED_TRACKERS_PATH.exists():
        return []
    try:
        with open(config.REGISTERED_TRACKERS_PATH) as f:
            data = yaml.safe_load(f)
    except (yaml.YAMLError, OSError):
        return []
    entries = data if isinstance(data, list) else []
    return [{**DEFAULT_BUILD_SETTINGS, **entry} for entry in entries]


def _save_unlocked(entries: list[dict]):
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(config.REGISTERED_TRACKERS_PATH, "w") as f:
        yaml.safe_dump(entries, f, sort_keys=False, allow_unicode=True)


def record_registration(eid_hex: str, pair_date: int):
    with _lock:
        entries = _load_unlocked()
        entries.insert(0, {"eid_hex": eid_hex, "pair_date": pair_date, **DEFAULT_BUILD_SETTINGS})
        _save_unlocked(entries[:_MAX_ENTRIES])


def record_build_settings(eid_hex: str, device_name: str, adv_interval_ms: int,
                           tx_power_dbm: int, tracking_protection: bool):
    with _lock:
        entries = _load_unlocked()
        settings = {
            "device_name": device_name, "adv_interval_ms": adv_interval_ms,
            "tx_power_dbm": tx_power_dbm, "tracking_protection": tracking_protection,
        }
        for entry in entries:
            if entry["eid_hex"] == eid_hex:
                entry.update(settings)
                break
        else:
            # EID wasn't produced by /register (typed in by hand) - still
            # worth remembering so a rebuild reuses it.
            entries.insert(0, {"eid_hex": eid_hex, "pair_date": 0, **settings})
        _save_unlocked(entries[:_MAX_ENTRIES])


def list_registered() -> list[dict]:
    with _lock:
        return _load_unlocked()
