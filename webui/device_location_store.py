"""The last location actually obtained for each device - written from both
places that call locate_device() (webui/routers/locate.py's manual button
and webui/scheduler.py's cron polling), so the Devices page can always show
something instead of going blank on every page load until someone clicks
Locate again. Same small-persisted-YAML shape as webui/settings_store.py;
there's nothing to migrate from, so no legacy-JSON fallback here.
"""

import threading

import yaml

from NovaApi.ExecuteAction.LocateTracker.decrypt_locations import create_map_links
from webui import config

_lock = threading.Lock()


def _migrate_location(loc: dict) -> dict:
    """A location persisted before the map-provider-links rename (see
    decrypt_locations.py's create_map_links) has no "map_links" at all - it
    still carries the old, single-provider "google_maps_link", or nothing.
    Backfill "map_links" from the coordinates already on file rather than
    leaving the Devices page's "Map" column permanently blank for every
    location fetched before that rename. Safe to run unconditionally on
    every load, same as webui/forwarders/config_store.py's migrations - a
    no-op once this device's next real locate overwrites the entry anyway."""
    if loc.get("is_semantic") or loc.get("map_links"):
        return loc
    if loc.get("latitude") is None or loc.get("longitude") is None:
        return loc
    migrated = {k: v for k, v in loc.items() if k != "google_maps_link"}
    migrated["map_links"] = create_map_links(loc["latitude"], loc["longitude"])
    return migrated


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
        entry = _load_unlocked().get(canonic_id)
        if not entry or "locations" not in entry:
            return None
        locations = [_migrate_location(loc) for loc in entry["locations"]]
        return {"locations": locations, "fetched_at": entry.get("fetched_at")}


def set_last_location(canonic_id: str, locations: list[dict], fetched_at: int):
    """Only ever call this with a non-empty `locations` - a timeout/failure
    must never clobber the last real result callers already have on file."""
    with _lock:
        data = _load_unlocked()
        entry = data.setdefault(canonic_id, {})
        entry["locations"] = locations
        entry["fetched_at"] = fetched_at
        _save_unlocked(data)
