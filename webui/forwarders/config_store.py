import logging

from webui import config, device_store
from webui.forwarders import latest_values_store
from webui.forwarders.presets import PRESETS

logger = logging.getLogger("webui.forwarders.config_store")


def _empty():
    return {"devices": {}}


def last_load_ok() -> bool:
    """Whether devices.yaml's most recent read actually succeeded, for
    /health (see webui/main.py) - a corrupt/unreadable file silently falls
    back to "0 devices configured", which is otherwise indistinguishable
    from a legitimately empty one. See webui/device_store.py."""
    return device_store.last_load_ok()


def _seconds_to_cron(seconds) -> str:
    # Best-effort translation of a legacy poll_interval_seconds value into an
    # equivalent cron expression, for devices saved before endpoints existed.
    seconds = seconds or config.DEFAULT_POLL_INTERVAL_S
    minutes = max(1, round(seconds / 60))
    if minutes <= 59:
        return f"*/{minutes} * * * *"
    hours = min(23, max(1, round(minutes / 60)))
    return f"0 */{hours} * * *"


def _fold_params_into_url(entry: dict) -> dict:
    """Query params used to be a separate table (see webui/forwarders/
    custom.py's old `params=` kwarg approach); the URL's own querystring is
    now the only source. One-time fold of any leftover "params" dict into a
    literal querystring appended to "url", preserving {{var}} tokens as-is
    (not percent-encoded) rather than escaping them - so an already-
    configured endpoint keeps sending the exact same request after
    upgrading. A no-op once "params" is gone, so safe to run unconditionally
    on every load."""
    params = entry.get("params")
    if not params:
        return entry
    folded = dict(entry)
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    sep = "&" if "?" in (folded.get("url") or "") else "?"
    folded["url"] = (folded.get("url") or "") + sep + qs
    folded.pop("params", None)
    return folded


def _migrate_legacy_endpoint(entry: dict) -> dict:
    """Upgrades one endpoint saved before the generic query-builder existed -
    a nested "traccar"/"phonetrack" sub-dict and no top-level "url" - into the
    current method/url/headers shape, baking the same query params the
    settings UI's presets now offer (see presets.py) directly into the URL.
    Also folds any leftover "params" dict (from after the generic
    query-builder existed, but before query params moved into the URL
    itself) into the URL the same way - see _fold_params_into_url. Both
    steps are no-ops on an endpoint that already looks like the current
    shape, so this is safe to run unconditionally on every load."""
    if not isinstance(entry, dict):
        return entry

    if "url" not in entry:
        etype = entry.get("type")
        migrated = {k: v for k, v in entry.items() if k not in ("traccar", "phonetrack")}

        if etype == "traccar":
            sub = entry.get("traccar") or {}
            base = (sub.get("url") or "").rstrip("/") + "/"
            migrated["method"] = "GET"
            migrated["url"] = (
                base + "?id={{device_id}}&lat={{latitude}}&lon={{longitude}}"
                "&timestamp={{google_timestamp}}&altitude={{altitude_m}}&accuracy={{accuracy_m}}"
            )
            migrated["headers"] = {}
            migrated["body_type"] = "none"
            migrated["body"] = ""
            migrated["variables"] = {"device_id": sub.get("device_id", "")}
        elif etype == "phonetrack":
            sub = entry.get("phonetrack") or {}
            # The old per-endpoint device_name override doesn't exist anymore
            # (see webui/forwarders/custom.py) - bake whatever it was set to
            # directly into the URL as a literal, which sends the exact same
            # request as before rather than silently switching to the account's
            # device alias for anyone who had it set to something else.
            base = (sub.get("base_url") or "").rstrip("/") + "/" + sub.get("device_name", "")
            migrated["method"] = "GET"
            migrated["url"] = (
                base + "?lat={{latitude}}&lon={{longitude}}"
                "&timestamp={{google_timestamp}}&alt={{altitude_m}}&acc={{accuracy_m}}"
            )
            migrated["headers"] = {}
            migrated["body_type"] = "none"
            migrated["body"] = ""
        else:
            # Unknown/missing legacy type - fall back to Custom/blank rather than
            # silently dropping the endpoint; the URL is just empty until the
            # user fills it back in themselves.
            preset = PRESETS["custom"]
            migrated.setdefault("type", "custom")
            migrated["method"] = preset["method"]
            migrated["url"] = preset["url"]
            migrated["headers"] = dict(preset["headers"])
            migrated["body_type"] = preset["body_type"]
            migrated["body"] = preset["body"]

        entry = migrated

    return _fold_params_into_url(entry)


def _strip_endpoint_state(entry: dict) -> dict:
    """Runtime state (last forward status/time, last-sent position,
    consecutive-failure streak) lives in its own file now, not here - see
    webui/forwarders/latest_values_store.py. An endpoint saved before that
    split still has these baked directly into it; drop them here the same
    "safe to run unconditionally on every load" way the rest of this
    module's migrations do. A no-op on an endpoint that's already clean."""
    if not any(k in entry for k in latest_values_store.STATE_KEYS):
        return entry
    return {k: v for k, v in entry.items() if k not in latest_values_store.STATE_KEYS}


def normalize_device_config(device_cfg: dict) -> dict:
    """Convert a pre-multi-endpoint device record into the current
    endpoints-list shape, and every endpoint in it into the current generic
    query-builder shape. A no-op (same object) on records that need neither."""
    if "endpoints" in device_cfg:
        migrated_endpoints = [_strip_endpoint_state(_migrate_legacy_endpoint(e)) for e in device_cfg["endpoints"]]
        if migrated_endpoints == device_cfg["endpoints"]:
            return device_cfg
        normalized = dict(device_cfg)
        normalized["endpoints"] = migrated_endpoints
        return normalized

    normalized = dict(device_cfg)
    destination = normalized.pop("destination", "none")
    old_traccar = normalized.pop("traccar", None)
    old_phonetrack = normalized.pop("phonetrack", None)
    # Runtime state on this pre-multi-endpoint shape gets dropped the same
    # way _strip_endpoint_state does below for every other shape - see
    # webui/forwarders/latest_values_store.py.
    normalized.pop("last_forward_status", None)
    normalized.pop("last_forward_time", None)
    poll_interval = normalized.pop("poll_interval_seconds", None)
    cron_expr = _seconds_to_cron(poll_interval)

    endpoints = []
    if destination == "traccar" and old_traccar:
        endpoints.append({"type": "traccar", "traccar": old_traccar, "cron": cron_expr})
    elif destination == "phonetrack" and old_phonetrack:
        endpoints.append({"type": "phonetrack", "phonetrack": old_phonetrack, "cron": cron_expr})
    # destination == "none" (or missing) -> empty list, forwarding stays disabled

    normalized["endpoints"] = [_strip_endpoint_state(_migrate_legacy_endpoint(e)) for e in endpoints]
    return normalized


# Bumped whenever normalize_device_config's migrations change what "current
# shape" means. A device's config saved under an older version gets migrated
# and written back the first time it's loaded, instead of being re-migrated
# (and never persisted) on every single load forever.
_SCHEMA_VERSION = 1


def load() -> dict:
    """The {"devices": {canonic_id: config_dict}} shape this module used to
    persist directly, projected from the shared devices.yaml (see
    webui/device_store.py) - kept for callers/tests that still think in
    terms of "just the forwarding config"."""
    devices = device_store.load()["devices"]
    normalized = {}
    changed = False
    for canonic_id, entry in devices.items():
        if "config" not in entry:
            continue
        cfg = normalize_device_config(entry["config"])
        normalized[canonic_id] = cfg
        if cfg != entry["config"]:
            changed = True
    if changed:
        for canonic_id, cfg in normalized.items():
            _set_config(canonic_id, cfg)
    return {"devices": normalized}


def _set_config(canonic_id: str, cfg: dict) -> None:
    device_store.mutate_device(canonic_id, lambda entry: entry.update(config=cfg))


def save(data: dict):
    """Full-replace of every device's config, same semantics this module
    always had - a device omitted from data["devices"] loses its config
    (but keeps its location/endpoint_state/staleness, which aren't this
    module's concern). One locked read-modify-write pass, not one per
    device."""
    wanted = data.get("devices", {})

    def _replace_all(devices: dict) -> None:
        for canonic_id in set(devices) | set(wanted):
            if canonic_id in wanted:
                devices.setdefault(canonic_id, {})["config"] = wanted[canonic_id]
            else:
                devices.get(canonic_id, {}).pop("config", None)

    device_store.mutate_devices(_replace_all)


def get_device_config(canonic_id: str) -> dict | None:
    entry = device_store.load()["devices"].get(canonic_id) or {}
    device_cfg = entry.get("config")
    return normalize_device_config(device_cfg) if device_cfg is not None else None


def set_device_config(canonic_id: str, device_config: dict):
    _set_config(canonic_id, device_config)


def all_devices() -> dict:
    devices = device_store.load()["devices"]
    return {
        canonic_id: normalize_device_config(entry["config"])
        for canonic_id, entry in devices.items()
        if "config" in entry
    }
