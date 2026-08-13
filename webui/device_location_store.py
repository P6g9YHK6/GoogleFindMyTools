"""The last location actually obtained for each device - written from both
places that call locate_device() (webui/routers/locate.py's manual button
and webui/scheduler.py's cron polling), so the Devices page can always show
something instead of going blank on every page load until someone clicks
Locate again. Same small-persisted-YAML shape as webui/settings_store.py;
there's nothing to migrate from, so no legacy-JSON fallback here.

Every stored location also carries a "first_seen" unix timestamp - see
set_last_location - so webui/scheduler.py can tell a genuinely new reading
apart from Google re-serving one it already returned in an earlier fetch
(it bundles stale cached reports alongside fresh ones sometimes) and skip
forwarding the latter again.
"""

import threading

import yaml

from NovaApi.ExecuteAction.LocateTracker.decrypt_locations import create_map_links
from webui import config

_lock = threading.Lock()


def _migrate_location(loc: dict, fallback_first_seen: int | None) -> dict:
    """A location persisted before the map-provider-links rename (see
    decrypt_locations.py's create_map_links) has no "map_links" at all - it
    still carries the old, single-provider "google_maps_link", or nothing.
    Backfill "map_links" from the coordinates already on file rather than
    leaving the Devices page's "Map" column permanently blank for every
    location fetched before that rename. Safe to run unconditionally on
    every load, same as webui/forwarders/config_store.py's migrations - a
    no-op once this device's next real locate overwrites the entry anyway.

    Also backfills "first_seen" (added after both of these) with the
    containing entry's own "fetched_at" - not exactly right (this reading
    could have first appeared earlier than that), but the closest guess
    available, and it self-corrects the moment this exact reading is
    fetched again."""
    migrated = loc
    if not migrated.get("is_semantic") and not migrated.get("map_links") \
            and migrated.get("latitude") is not None and migrated.get("longitude") is not None:
        migrated = {k: v for k, v in migrated.items() if k != "google_maps_link"}
        migrated["map_links"] = create_map_links(migrated["latitude"], migrated["longitude"])
    if migrated.get("first_seen") is None and fallback_first_seen is not None:
        if migrated is loc:
            migrated = dict(migrated)
        migrated["first_seen"] = fallback_first_seen
    return migrated


def _location_key(loc: dict) -> tuple:
    """Identifies "the same reading" across fetches - the fields that
    meaningfully distinguish one location report from another, ignoring
    cosmetic ones like map_links/accuracy that don't change what was
    actually observed."""
    return (loc.get("time"), loc.get("latitude"), loc.get("longitude"), loc.get("status"), loc.get("semantic_name"))


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
    ever been obtained for this device. Each location carries "first_seen" -
    see set_last_location."""
    with _lock:
        entry = _load_unlocked().get(canonic_id)
        if not entry or "locations" not in entry:
            return None
        locations = [_migrate_location(loc, entry.get("fetched_at")) for loc in entry["locations"]]
        return {"locations": locations, "fetched_at": entry.get("fetched_at")}


def set_last_location(canonic_id: str, locations: list[dict], fetched_at: int) -> list[dict]:
    """Only ever call this with a non-empty `locations` - a timeout/failure
    must never clobber the last real result callers already have on file.

    Stamps each location with "first_seen": the unix timestamp it was first
    observed. A reading whose _location_key matches one already on file (or
    one already processed earlier in this same `locations` batch - Google
    occasionally bundles the same stale report twice in one response) keeps
    that earlier first_seen instead of getting a fresh one.

    Each dict in the *returned* list also carries a transient "_new_this_fetch"
    bool - True the first time this exact reading's key has ever been seen,
    False if it (or an earlier entry in this same batch) already existed.
    webui/scheduler.py's poll loop pops that off and uses it to skip
    forwarding a reading Google already reported before. It's deliberately
    not part of what gets persisted/returned from get_last_location, and
    deliberately not just "first_seen == fetched_at" - two calls landing in
    the same wall-clock second (fetched_at only has 1-second resolution)
    would otherwise be indistinguishable from a truly new reading.

    Returns the stamped locations list actually persisted (plus that one
    transient key)."""
    with _lock:
        data = _load_unlocked()
        entry = data.setdefault(canonic_id, {})
        previously_seen = {_location_key(loc): loc.get("first_seen") for loc in entry.get("locations", [])}

        stamped = []
        persisted = []
        for loc in locations:
            key = _location_key(loc)
            is_new = key not in previously_seen
            first_seen = fetched_at if is_new else previously_seen[key]
            previously_seen[key] = first_seen
            persisted.append({**loc, "first_seen": first_seen})
            stamped.append({**loc, "first_seen": first_seen, "_new_this_fetch": is_new})

        entry["locations"] = persisted
        entry["fetched_at"] = fetched_at
        _save_unlocked(data)
        return stamped
