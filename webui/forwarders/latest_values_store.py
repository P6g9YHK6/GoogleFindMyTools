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

from webui import config
from webui.yaml_io import read_yaml_dict, write_yaml_dict

_lock = threading.Lock()

# Every field policy.py's _record_forward_result computes - the complete set
# that used to live directly on a saved endpoint before this file existed.
STATE_KEYS = (
    "last_forward_status", "last_forward_time",
    "last_sent_lat", "last_sent_lon", "last_sent_fix_time",
    "consecutive_failures",
)

# Per-device (not per-endpoint-URL) staleness config + alert-dedup state -
# see webui/staleness.py. Stored as a sibling entry under each device's own
# dict here, under this reserved pseudo-key rather than a real endpoint URL -
# every real key in that dict is always a literal "http(s)://..." endpoint
# URL (see get_endpoint_state/set_endpoint_state below), so this can never
# collide with one. Lives here rather than in forwarding.yaml (see
# webui/forwarders/config_store.py) for the same reason every other
# runtime-computed field already does: it's state, not configuration a human
# typed in, even though (unlike the rest of this file) some of it - the
# threshold/repeat/message/mute fields - is itself user-editable, just from
# the Staleness page rather than the Settings page.
_STALENESS_KEY = "__staleness__"


def get_device_staleness(canonic_id: str) -> dict:
    """Whatever's been recorded for this device's staleness tracking - {} if
    it's never been configured (i.e. tracking is off, same as an explicit
    "enabled": False would mean)."""
    with _lock:
        return dict((_load_unlocked().get(canonic_id) or {}).get(_STALENESS_KEY) or {})


def set_device_staleness(canonic_id: str, state: dict):
    """Overwrites this device's recorded staleness state wholesale, same
    convention as set_endpoint_state below."""
    with _lock:
        data = _load_unlocked()
        data.setdefault(canonic_id, {})[_STALENESS_KEY] = state
        _save_unlocked(data)


def _load_unlocked() -> dict:
    data, _ok = read_yaml_dict(config.LATEST_VALUES_PATH)
    return data


def _save_unlocked(data: dict):
    write_yaml_dict(config.LATEST_VALUES_PATH, data)


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
    hygiene. _STALENESS_KEY is never a real endpoint URL (see
    get_device_staleness above) - always kept here regardless of `urls`, or
    every Settings-page save would silently wipe a device's staleness
    config/state."""
    with _lock:
        data = _load_unlocked()
        if canonic_id not in data:
            return
        kept = {
            url: state for url, state in data[canonic_id].items()
            if url in urls or url == _STALENESS_KEY
        }
        if kept == data[canonic_id]:
            return
        if kept:
            data[canonic_id] = kept
        else:
            data.pop(canonic_id, None)
        _save_unlocked(data)
