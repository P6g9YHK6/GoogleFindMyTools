"""Persisted app-wide settings (config.yaml) - the query throttle and Apprise
notification settings that used to be env-var-only (see webui/config.py).
A value here overrides its env-var default; nothing set here just falls
back to the env var/hardcoded default, so upgrading with no config.yaml
present yet changes nothing.
"""

import os
import threading

import yaml

from webui import config

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
    }


def load() -> dict:
    with _lock:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        defaults = _defaults()
        if not config.APP_SETTINGS_PATH.exists():
            return defaults
        try:
            with open(config.APP_SETTINGS_PATH) as f:
                data = yaml.safe_load(f)
        except (yaml.YAMLError, OSError):
            return defaults
        if not isinstance(data, dict):
            return defaults
        defaults.update(data)
        return defaults


def save(data: dict):
    with _lock:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(config.APP_SETTINGS_PATH, "w") as f:
            yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)


def apprise_env() -> dict:
    """The current Apprise settings, shaped as the env-var dict
    webui.notify.configure_apprise_logging() expects."""
    settings = load()
    return {
        "APPRISE_URLS": settings["apprise_urls"],
        "APPRISE_NOTIFY_LEVEL": settings["apprise_notify_level"],
    }
