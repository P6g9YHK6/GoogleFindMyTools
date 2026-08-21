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

And remembers the last identity (display name/device type/manufacturer/
model/image URL) submitted on the Register form itself - see
webui/identity_validation.py. Unlike the build settings above, this isn't
per-EID (it's chosen before a new EID exists), so it's a single top-level
record rather than part of the entries list.

Only the public EID and these settings are stored - never the private eik
(see SpotApi/CreateBleDevice/create_ble_device.py, which never returns eik
to the webui at all), so this is no more sensitive than the values the
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

# What the Register form's identity fields look like before anyone has ever
# customized them - matches SpotApi.CreateBleDevice.create_ble_device's
# register_esp32() defaults exactly, so a fresh install (or an existing one
# from before this feature) registers identically to before.
DEFAULT_IDENTITY = {
    "display_name": "GoogleFindMyTools µC",
    "device_type": "DEVICE_TYPE_BEACON",
    "manufacturer_name": "GoogleFindMyTools",
    "model_name": "µC",
    "image_url": "https://docs.espressif.com/projects/esp-idf/en/v4.3/esp32/_images/esp32-DevKitM-1-isometric.png",
}


def _load_unlocked() -> dict:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not config.REGISTERED_TRACKERS_PATH.exists():
        return {"entries": [], "last_identity": {}}
    try:
        with open(config.REGISTERED_TRACKERS_PATH) as f:
            data = yaml.safe_load(f)
    except (yaml.YAMLError, OSError):
        return {"entries": [], "last_identity": {}}
    entries: list[dict]
    last_identity: dict
    if isinstance(data, list):
        # Legacy shape from before last_identity existed - a bare list of
        # entries. Loads fine as-is; the next write upgrades the file to the
        # dict shape below, no separate migration step needed.
        entries, last_identity = data, {}
    elif isinstance(data, dict):
        raw_entries, raw_identity = data.get("entries"), data.get("last_identity")
        entries = raw_entries if isinstance(raw_entries, list) else []
        last_identity = raw_identity if isinstance(raw_identity, dict) else {}
    else:
        entries, last_identity = [], {}
    entries = [{**DEFAULT_BUILD_SETTINGS, **entry} for entry in entries]
    return {"entries": entries, "last_identity": last_identity}


def _save_unlocked(data: dict):
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(config.REGISTERED_TRACKERS_PATH, "w") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)


def record_registration(eid_hex: str, pair_date: int):
    with _lock:
        data = _load_unlocked()
        data["entries"].insert(0, {"eid_hex": eid_hex, "pair_date": pair_date, **DEFAULT_BUILD_SETTINGS})
        data["entries"] = data["entries"][:_MAX_ENTRIES]
        _save_unlocked(data)


def record_build_settings(eid_hex: str, device_name: str, adv_interval_ms: int,
                           tx_power_dbm: int, tracking_protection: bool):
    with _lock:
        data = _load_unlocked()
        settings = {
            "device_name": device_name, "adv_interval_ms": adv_interval_ms,
            "tx_power_dbm": tx_power_dbm, "tracking_protection": tracking_protection,
        }
        for entry in data["entries"]:
            if entry["eid_hex"] == eid_hex:
                entry.update(settings)
                break
        else:
            # EID wasn't produced by /register (typed in by hand) - still
            # worth remembering so a rebuild reuses it.
            data["entries"].insert(0, {"eid_hex": eid_hex, "pair_date": 0, **settings})
        data["entries"] = data["entries"][:_MAX_ENTRIES]
        _save_unlocked(data)


def list_registered() -> list[dict]:
    with _lock:
        return _load_unlocked()["entries"]


def load_last_identity() -> dict:
    with _lock:
        return {**DEFAULT_IDENTITY, **_load_unlocked()["last_identity"]}


def record_identity(display_name: str, device_type: str, manufacturer_name: str,
                     model_name: str, image_url: str):
    with _lock:
        data = _load_unlocked()
        data["last_identity"] = {
            "display_name": display_name, "device_type": device_type,
            "manufacturer_name": manufacturer_name, "model_name": model_name,
            "image_url": image_url,
        }
        _save_unlocked(data)
