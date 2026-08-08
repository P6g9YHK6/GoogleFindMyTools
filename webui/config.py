import os
import pathlib

# noVNC/websockify run in this same container now (see webui/browser_provisioning.py),
# only while a login is actually in progress. The web app still proxies it through
# its own origin (webui/routers/vnc_proxy.py) rather than exposing it directly.
BROWSER_NOVNC_URL = os.environ.get("BROWSER_NOVNC_URL", "http://localhost:6901")
WEBUI_PORT = int(os.environ.get("WEBUI_PORT", "4321"))

# Where the on-demand Chrome/Xvfb/noVNC stack lives - a tmpfs mount in Docker,
# wiped on every container restart. See webui/browser_provisioning.py.
GFMT_BROWSER_RUNTIME_DIR = os.environ.get("GFMT_BROWSER_RUNTIME_DIR", "/run/gfmt-browser")
# How long to wait for a login to complete (or the page to be abandoned)
# before tearing the whole provisioned stack back down.
GFMT_BROWSER_IDLE_TIMEOUT_S = int(os.environ.get("GFMT_BROWSER_IDLE_TIMEOUT_S", "600"))
DEFAULT_POLL_INTERVAL_S = int(os.environ.get("DEFAULT_POLL_INTERVAL_S", "300"))
LOCATE_CONCURRENCY = int(os.environ.get("LOCATE_CONCURRENCY", "5"))
LOCATE_TIMEOUT_S = int(os.environ.get("LOCATE_TIMEOUT_S", "60"))

# Account-wide throttle for every blocking call to Google's own backend
# (device list, locate, sound, register - see webui/deps.py's run_blocking,
# the one choke point they all go through). At most QUERY_THROTTLE_MAX
# requests within any rolling QUERY_THROTTLE_WINDOW_S-second window (the
# window is configurable, not hardcoded to a fixed "per minute"), plus at
# least QUERY_MIN_SPREAD_S seconds between any two consecutive requests.
# Requests over either limit wait their turn in a queue instead of failing -
# see webui/deps.py's QueryGate and the live counter on the Config page.
# 0 disables that particular limit.
QUERY_THROTTLE_MAX = int(os.environ.get("QUERY_THROTTLE_MAX", "20"))
QUERY_THROTTLE_WINDOW_S = float(os.environ.get("QUERY_THROTTLE_WINDOW_S", "60"))
QUERY_MIN_SPREAD_S = float(os.environ.get("QUERY_MIN_SPREAD_S", "1"))

# If both are set, the whole web UI (including the WebSocket) requires this
# username/password pair via HTTP Basic Auth. Unset by default - see README.
HTTP_USER = os.environ.get("HTTP_USER")
HTTP_PASSWORD = os.environ.get("HTTP_PASSWORD")

# Lets forwarding_config.json live in a mounted directory (e.g. in Docker,
# alongside GFMT_SECRETS_DIR under the same volume) instead of always sitting
# next to this module - see Auth/token_cache.py for the same pattern.
DATA_DIR = pathlib.Path(os.environ.get("GFMT_DATA_DIR") or (pathlib.Path(__file__).parent / "data"))
FORWARDING_CONFIG_PATH = DATA_DIR / "forwarding.yaml"
# Pre-YAML location - config_store.py reads this once to migrate, then never again.
FORWARDING_CONFIG_LEGACY_JSON_PATH = DATA_DIR / "forwarding_config.json"
FORWARD_LOG_PATH = DATA_DIR / "forward.log"
# Pre-.log location - log_store.py reads this once to migrate, then never again.
FORWARD_LOG_LEGACY_JSON_PATH = DATA_DIR / "forward_log.json"
FORWARD_LOG_MAX_ENTRIES = int(os.environ.get("FORWARD_LOG_MAX_ENTRIES", "1000"))
# Persisted overrides for the throttle/Apprise settings below - see
# webui/settings_store.py and the Config page.
APP_SETTINGS_PATH = DATA_DIR / "config.yaml"

# Every INFO-or-above log record app-wide (not just forwarding attempts) -
# see webui/log_capture.py and the System Log page. Bounded the same way as
# forward.log, just with more headroom since it captures far more than one
# category of event.
SYSTEM_LOG_PATH = DATA_DIR / "system.log"
SYSTEM_LOG_MAX_ENTRIES = int(os.environ.get("SYSTEM_LOG_MAX_ENTRIES", "5000"))

# The last location actually obtained for each device, regardless of whether
# it came from a manual Locate click or a scheduled poll - see
# webui/device_location_store.py and the Devices page.
DEVICE_LOCATIONS_PATH = DATA_DIR / "device_locations.yaml"
