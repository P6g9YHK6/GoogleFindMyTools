import json
import threading

import yaml

from webui import config
from webui.forwarders.presets import PRESETS

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


def _migrate_legacy_endpoint(entry: dict) -> dict:
    """Upgrades one endpoint saved before the generic query-builder existed -
    a nested "traccar"/"phonetrack" sub-dict and no top-level "url" - into the
    current method/url/params/headers/variables shape, using the same preset
    templates the settings UI now offers (see presets.py). A no-op on
    endpoints that already look like the current shape, so this is safe to
    run unconditionally on every load."""
    if not isinstance(entry, dict) or "url" in entry:
        return entry

    etype = entry.get("type")
    migrated = {k: v for k, v in entry.items() if k not in ("traccar", "phonetrack")}

    if etype == "traccar":
        sub = entry.get("traccar") or {}
        preset = PRESETS["traccar"]
        migrated["method"] = preset["method"]
        migrated["url"] = (sub.get("url") or "").rstrip("/") + "/"
        migrated["params"] = dict(preset["params"])
        migrated["headers"] = {}
        migrated["body_type"] = "none"
        migrated["body"] = ""
        migrated["variables"] = {"device_id": sub.get("device_id", "")}
    elif etype == "phonetrack":
        sub = entry.get("phonetrack") or {}
        preset = PRESETS["phonetrack"]
        migrated["method"] = preset["method"]
        # The old per-endpoint device_name override doesn't exist anymore
        # (see webui/forwarders/custom.py) - bake whatever it was set to
        # directly into the URL as a literal, which sends the exact same
        # request as before rather than silently switching to the account's
        # device alias for anyone who had it set to something else.
        migrated["url"] = (sub.get("base_url") or "").rstrip("/") + "/" + sub.get("device_name", "")
        migrated["params"] = dict(preset["params"])
        migrated["headers"] = {}
        migrated["body_type"] = "none"
        migrated["body"] = ""
        migrated["variables"] = {}
    else:
        # Unknown/missing legacy type - fall back to Custom/blank rather than
        # silently dropping the endpoint; the URL is just empty until the
        # user fills it back in themselves.
        preset = PRESETS["custom"]
        migrated.setdefault("type", "custom")
        migrated["method"] = preset["method"]
        migrated["url"] = preset["url"]
        migrated["params"] = dict(preset["params"])
        migrated["headers"] = dict(preset["headers"])
        migrated["body_type"] = preset["body_type"]
        migrated["body"] = preset["body"]
        migrated["variables"] = dict(preset["variables"])

    return migrated


def normalize_device_config(device_cfg: dict) -> dict:
    """Convert a pre-multi-endpoint device record into the current
    endpoints-list shape, and every endpoint in it into the current generic
    query-builder shape. A no-op (same object) on records that need neither."""
    if "endpoints" in device_cfg:
        migrated_endpoints = [_migrate_legacy_endpoint(e) for e in device_cfg["endpoints"]]
        if migrated_endpoints == device_cfg["endpoints"]:
            return device_cfg
        normalized = dict(device_cfg)
        normalized["endpoints"] = migrated_endpoints
        return normalized

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

    normalized["endpoints"] = [_migrate_legacy_endpoint(e) for e in endpoints]
    return normalized


def _migrate_from_legacy_json() -> dict | None:
    """One-time upgrade path from the pre-YAML forwarding_config.json - read it
    once, write it straight back out as forwarding.yaml, and leave the old
    file in place untouched (as a backup, and so a downgrade isn't a hard
    break). Every load() after that first migration hits the YAML file
    directly and never looks at the JSON file again."""
    if not config.FORWARDING_CONFIG_LEGACY_JSON_PATH.exists():
        return None
    try:
        with open(config.FORWARDING_CONFIG_LEGACY_JSON_PATH) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    data.setdefault("devices", {})
    _save(data)
    return data


def load() -> dict:
    with _lock:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        if not config.FORWARDING_CONFIG_PATH.exists():
            return _migrate_from_legacy_json() or _empty()
        try:
            with open(config.FORWARDING_CONFIG_PATH) as f:
                data = yaml.safe_load(f)
        except (yaml.YAMLError, OSError):
            return _empty()
        if not isinstance(data, dict):
            return _empty()
        data.setdefault("devices", {})
        return data


def _save(data: dict):
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(config.FORWARDING_CONFIG_PATH, "w") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)


def save(data: dict):
    with _lock:
        _save(data)


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
