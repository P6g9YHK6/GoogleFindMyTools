"""Per-endpoint forwarding runtime state - last status/time, last-sent
position, consecutive-failure streak - split out of forwarding.yaml (see
webui/forwarders/config_store.py) so that file stays pure configuration, not
a growing pile of history.

Keyed by the endpoint's own URL rather than its position in the endpoints
list, so a saved endpoint's state naturally survives being reordered, and
just as naturally starts fresh if that endpoint's URL actually changes (a
differently-targeted request is a new "endpoint" as far as the skip-if-
close/skip-if-stale gates and the forward log are concerned - see
webui/forwarders/policy.py) - no separate "did this position's URL change"
reconciliation step needed on save.

Same small-persisted-YAML shape as webui/device_location_store.py.
"""

import threading

import yaml

from webui import config

_lock = threading.Lock()

# Every field policy.py's _record_forward_result computes - the complete set
# that used to live directly on a saved endpoint before this file existed.
STATE_KEYS = (
    "last_forward_status", "last_forward_time",
    "last_sent_lat", "last_sent_lon", "last_sent_fix_time",
    "consecutive_failures",
)


def _load_unlocked() -> dict:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not config.LATEST_VALUES_PATH.exists():
        return {}
    try:
        with open(config.LATEST_VALUES_PATH) as f:
            data = yaml.safe_load(f)
    except (yaml.YAMLError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_unlocked(data: dict):
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(config.LATEST_VALUES_PATH, "w") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)


def get_endpoint_state(canonic_id: str, url: str) -> dict:
    """Whatever's been recorded for this device's endpoint at this URL - {}
    if nothing has ever been sent through it (or its URL just changed)."""
    if not url:
        return {}
    with _lock:
        return dict((_load_unlocked().get(canonic_id) or {}).get(url) or {})


def set_endpoint_state(canonic_id: str, url: str, state: dict):
    """Overwrites this device/URL's recorded state wholesale - callers build
    the full dict (see webui/forwarders/policy.py's _record_forward_result)
    rather than patching individual keys."""
    if not url:
        return
    with _lock:
        data = _load_unlocked()
        data.setdefault(canonic_id, {})[url] = state
        _save_unlocked(data)


def prune_to_urls(canonic_id: str, urls: set[str]):
    """Drops recorded state for any of this device's URLs that aren't one of
    its current endpoints' anymore - called after a save (see
    routers/settings.py) so a removed or rewritten endpoint doesn't leave an
    orphaned entry sitting around forever. Not required for correctness
    (get_endpoint_state on a URL nothing recognizes just returns {}), only
    hygiene."""
    with _lock:
        data = _load_unlocked()
        if canonic_id not in data:
            return
        kept = {url: state for url, state in data[canonic_id].items() if url in urls}
        if kept == data[canonic_id]:
            return
        if kept:
            data[canonic_id] = kept
        else:
            data.pop(canonic_id, None)
        _save_unlocked(data)
