"""Per-endpoint forwarding runtime state - last status/time, last-sent
position, consecutive-failure streak - and per-device staleness tracking
config/state. Backed by the shared devices.yaml (see webui/device_store.py),
under this module's own "endpoint_state" (keyed by endpoint URL) and
"staleness" sub-keys - kept separate from "config" (see
webui/forwarders/config_store.py) so that stays pure configuration, not a
growing pile of history.

Keyed by the endpoint's own URL rather than its position in the endpoints
list, so a saved endpoint's state naturally survives being reordered, and
just as naturally starts fresh if that endpoint's URL actually changes (a
differently-targeted request is a new "endpoint" as far as the skip-if-
close/skip-if-stale gates and the forward log are concerned - see
webui/forwarders/policy.py) - no separate "did this position's URL change"
reconciliation step needed on save.
"""

from webui import device_store

# Every field policy.py's _record_forward_result computes - the complete set
# that used to live directly on a saved endpoint before this file existed.
STATE_KEYS = (
    "last_forward_status", "last_forward_time",
    "last_sent_lat", "last_sent_lon", "last_sent_fix_time",
    "consecutive_failures",
)


def get_device_staleness(canonic_id: str) -> dict:
    """Whatever's been recorded for this device's staleness tracking - {} if
    it's never been configured (i.e. tracking is off, same as an explicit
    "enabled": False would mean)."""
    entry = device_store.load()["devices"].get(canonic_id) or {}
    return dict(entry.get("staleness") or {})


def set_device_staleness(canonic_id: str, state: dict):
    """Overwrites this device's recorded staleness state wholesale, same
    convention as set_endpoint_state below."""
    device_store.mutate_device(canonic_id, lambda entry: entry.update(staleness=state))


def get_endpoint_state(canonic_id: str, url: str) -> dict:
    """Whatever's been recorded for this device's endpoint at this URL - {}
    if nothing has ever been sent through it (or its URL just changed)."""
    if not url:
        return {}
    entry = device_store.load()["devices"].get(canonic_id) or {}
    return dict((entry.get("endpoint_state") or {}).get(url) or {})


def set_endpoint_state(canonic_id: str, url: str, state: dict):
    """Overwrites this device/URL's recorded state wholesale - callers build
    the full dict (see webui/forwarders/policy.py's _record_forward_result)
    rather than patching individual keys."""
    if not url:
        return

    def _set(entry: dict) -> None:
        entry.setdefault("endpoint_state", {})[url] = state

    device_store.mutate_device(canonic_id, _set)


def prune_to_urls(canonic_id: str, urls: set[str]):
    """Drops recorded state for any of this device's URLs that aren't one of
    its current endpoints' anymore - called after a save (see
    routers/settings.py) so a removed or rewritten endpoint doesn't leave an
    orphaned entry sitting around forever. Not required for correctness
    (get_endpoint_state on a URL nothing recognizes just returns {}), only
    hygiene."""

    def _prune(entry: dict) -> None:
        endpoint_state = entry.get("endpoint_state")
        if not endpoint_state:
            return
        kept = {url: state for url, state in endpoint_state.items() if url in urls}
        if kept:
            entry["endpoint_state"] = kept
        else:
            entry.pop("endpoint_state", None)

    device_store.mutate_device(canonic_id, _prune)
