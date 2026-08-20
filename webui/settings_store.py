"""Persisted app-wide settings (config.yaml) - the query throttle and Apprise
notification settings that used to be env-var-only (see webui/config.py).
A value here overrides its env-var default; nothing set here just falls
back to the env var/hardcoded default, so upgrading with no config.yaml
present yet changes nothing.
"""

import os
import threading

from webui import config
from webui.yaml_io import read_yaml_dict, write_yaml_dict

_lock = threading.Lock()


def _defaults() -> dict:
    return {
        "query_throttle_max": config.QUERY_THROTTLE_MAX,
        "query_throttle_window_s": config.QUERY_THROTTLE_WINDOW_S,
        "query_min_spread_s": config.QUERY_MIN_SPREAD_S,
        "apprise_urls": os.environ.get("APPRISE_URLS", ""),
        "apprise_notify_level": os.environ.get("APPRISE_NOTIFY_LEVEL", "WARNING"),
        # Devices page's "Last locate result" column (and its map pins) -
        # see webui/device_location_store.py's most_recent_only and its
        # callers in webui/routers/devices.py and webui/routers/locate.py.
        # Unrelated to forwarding's own per-endpoint only_most_recent
        # toggle (webui/forwarders/policy.py) - this is purely a display
        # preference, not tied to any endpoint's config.
        "devices_page_most_recent_only": True,
        # How often webui/staleness.py's independent background sweep
        # re-checks every device's last-known fix age - separate from any
        # device's own cron schedule (see that module's own docstring for
        # why it has to be). Applies live, same as the throttle settings
        # above - no restart needed.
        "staleness_sweep_interval_s": 3600,
        # Fixed coordinates for named SEMANTIC locations (e.g. "Nest Mini -
        # Living Room") - Google never reports lat/lon for these, so without
        # an entry here they're skipped by every forwarder (see
        # webui/forwarders/semantic_map.py). Global rather than per-device:
        # a named smart-home device's position doesn't change depending on
        # which tracker reports being near it. {name: {"latitude": float,
        # "longitude": float, "match_mode": "full"|"partial"}}. match_mode
        # defaults to "full" (exact match) when absent, so entries saved
        # before this field existed keep behaving the same way.
        "semantic_location_map": {},
    }


def load() -> dict:
    with _lock:
        defaults = _defaults()
        data, ok = read_yaml_dict(config.APP_SETTINGS_PATH)
        if not ok:
            return defaults
        defaults.update(data)
        return defaults


def save(data: dict):
    with _lock:
        write_yaml_dict(config.APP_SETTINGS_PATH, data)


def apprise_env() -> dict:
    """The current Apprise settings, shaped as the env-var dict
    webui.notify.configure_apprise_logging() expects."""
    settings = load()
    return {
        "APPRISE_URLS": settings["apprise_urls"],
        "APPRISE_NOTIFY_LEVEL": settings["apprise_notify_level"],
    }
