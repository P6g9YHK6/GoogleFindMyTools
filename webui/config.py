import os
import pathlib
import time

# noVNC/websockify run in this same container now (see webui/browser_provisioning.py),
# only while a login is actually in progress. The web app still proxies it through
# its own origin (webui/routers/vnc_proxy.py) rather than exposing it directly.
BROWSER_NOVNC_URL = os.environ.get("BROWSER_NOVNC_URL", "http://localhost:6901")

# Where the on-demand Chrome/Xvfb/noVNC stack lives - a tmpfs mount in Docker,
# wiped on every container restart. See webui/browser_provisioning.py.
GFMT_BROWSER_RUNTIME_DIR = os.environ.get("GFMT_BROWSER_RUNTIME_DIR", "/run/gfmt-browser")
# How long to wait for a login to complete (or the page to be abandoned)
# before tearing the whole provisioned stack back down.
GFMT_BROWSER_IDLE_TIMEOUT_S = int(os.environ.get("GFMT_BROWSER_IDLE_TIMEOUT_S", "600"))
# Bounds the Chrome for Testing zip download (webui/browser_provisioning.py) -
# without this, a slow/filtered/blocked network path to storage.googleapis.com
# hangs the whole sign-in flow forever with no error, since urlretrieve has no
# timeout of its own.
GFMT_BROWSER_DOWNLOAD_TIMEOUT_S = int(os.environ.get("GFMT_BROWSER_DOWNLOAD_TIMEOUT_S", "300"))
DEFAULT_POLL_INTERVAL_S = int(os.environ.get("DEFAULT_POLL_INTERVAL_S", "300"))
# How long a device-list fetch (Nova's slow device-list call, see
# NovaApi/ListDevices/nbe_list_devices.py's request_device_list()) is reused
# for repeated page loads before re-fetching - see webui/device_list_cache.py.
# Short enough that "did I just register a tracker" or "did something
# actually change" still feels live.
DEVICE_LIST_CACHE_TTL_S = float(os.environ.get("DEVICE_LIST_CACHE_TTL_S", "8"))
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

# Opt-in self-signed HTTPS - see webui/tls.py and webui/serve.py (the
# Docker image's actual entrypoint, see docker/web/Dockerfile). A toggle,
# not a dual HTTP+HTTPS listener: exact "1" match (not a truthy-string
# check) matching the GFMT_NONINTERACTIVE convention elsewhere, so
# HTTPS_ENABLED=0 can't accidentally enable it. Unset by default - see
# README.
HTTPS_ENABLED = os.environ.get("HTTPS_ENABLED") == "1"
# Bring-your-own-cert escape hatch - if either is set, webui/tls.py requires
# both files to actually exist (fails loudly rather than silently falling
# back to a self-signed cert the operator didn't ask for). Unset means
# "generate and persist a self-signed cert instead" - see TLS_CERT_PATH/
# TLS_KEY_PATH below.
GFMT_TLS_CERT_PATH = os.environ.get("GFMT_TLS_CERT_PATH")
GFMT_TLS_KEY_PATH = os.environ.get("GFMT_TLS_KEY_PATH")
# Extra hostnames/IPs (comma-separated) to add to the generated self-signed
# cert's Subject Alternative Names, beyond localhost/127.0.0.1/::1 - set
# this to your LAN hostname or static IP if you reach this box by either.
GFMT_TLS_SAN = os.environ.get("GFMT_TLS_SAN")
# How long a generated self-signed cert is valid for. Deliberately not a
# much longer "set and forget" duration: Apple's ATS policy hard-caps
# accepted TLS server cert validity at 825 days, even for a cert the user
# manually trusts - a longer-lived one would just keep silently failing in
# Safari/iOS/macOS with no obvious error pointing at why.
GFMT_TLS_VALIDITY_DAYS = int(os.environ.get("GFMT_TLS_VALIDITY_DAYS", "825"))

# Lets forwarding_config.json live in a mounted directory (e.g. in Docker,
# alongside GFMT_SECRETS_DIR under the same volume) instead of always sitting
# next to this module - see Auth/token_cache.py for the same pattern.
DATA_DIR = pathlib.Path(os.environ.get("GFMT_DATA_DIR") or (pathlib.Path(__file__).parent / "data"))

# One file, keyed by canonic device ID, backing config_store.py,
# device_location_store.py and latest_values_store.py - see
# webui/device_store.py. FORWARDING_CONFIG_PATH/DEVICE_LOCATIONS_PATH/
# LATEST_VALUES_PATH/their legacy JSON below are the pre-fusion locations -
# device_store.py reads them once to migrate into DEVICES_PATH, then never
# again.
DEVICES_PATH = DATA_DIR / "devices.yaml"
FORWARDING_CONFIG_PATH = DATA_DIR / "forwarding.yaml"
FORWARDING_CONFIG_LEGACY_JSON_PATH = DATA_DIR / "forwarding_config.json"
FORWARD_LOG_PATH = DATA_DIR / "forward.log"
# Pre-.log location - log_store.py reads this once to migrate, then never again.
FORWARD_LOG_LEGACY_JSON_PATH = DATA_DIR / "forward_log.json"
FORWARD_LOG_MAX_ENTRIES = int(os.environ.get("FORWARD_LOG_MAX_ENTRIES", "1000"))
# Persisted overrides for the throttle/Apprise settings below - see
# webui/settings_store.py and the Config page.
APP_SETTINGS_PATH = DATA_DIR / "config.yaml"

# Every INFO-or-above log record app-wide (not just forwarding attempts) -
# see webui/log_capture.py and the Logs page (webui/routers/logs.py).
# Bounded the same way as forward.log, just with more headroom since it
# captures far more than one category of event.
SYSTEM_LOG_PATH = DATA_DIR / "system.log"
SYSTEM_LOG_MAX_ENTRIES = int(os.environ.get("SYSTEM_LOG_MAX_ENTRIES", "5000"))

# Pre-fusion location for device_location_store.py's data - see DEVICES_PATH.
DEVICE_LOCATIONS_PATH = DATA_DIR / "device_locations.yaml"

# Pre-fusion location for latest_values_store.py's data - see DEVICES_PATH.
LATEST_VALUES_PATH = DATA_DIR / "latest_values.yaml"

# Every advertisement key ever produced by /register, so the Firmware page
# can offer them again later instead of making the user copy-paste one it
# only ever showed once - see webui/firmware_store.py. Safe to persist: it's
# the public EID, not the private eik (see SpotApi/CreateBleDevice/create_ble_device.py,
# which never returns eik at all).
REGISTERED_TRACKERS_PATH = DATA_DIR / "registered_trackers.yaml"

# Bounds a single `idf.py build` invocation kicked off from the Firmware page
# - see webui/firmware_build.py. Generous: a cold ESP-IDF build can take
# several minutes.
GFMT_FIRMWARE_BUILD_TIMEOUT_S = int(os.environ.get("GFMT_FIRMWARE_BUILD_TIMEOUT_S", "900"))

# Default location for a generated self-signed cert/key (see webui/tls.py) -
# flat in DATA_DIR like everything else here, so the existing volume mount
# covers it with no new subfolder. Only used when GFMT_TLS_CERT_PATH/
# GFMT_TLS_KEY_PATH above aren't set.
TLS_CERT_PATH = DATA_DIR / "tls_cert.pem"
TLS_KEY_PATH = DATA_DIR / "tls_key.pem"

# Baked in at image build time (see docker/web/Dockerfile and
# .github/workflows/docker-publish.yml) so the footer can show what's
# actually running without the container reading back its own image's OCI
# labels. "dev" means a local/dev build with no --build-arg passed - see
# webui/templating.py, which treats that as "no real commit to link to".
GFMT_BUILD_SHA = os.environ.get("GFMT_BUILD_SHA", "dev")
GFMT_BUILD_DATE = os.environ.get("GFMT_BUILD_DATE", "")

# Process start time, for the footer's uptime display and /metrics'
# gfmt_uptime_seconds (webui/routers/metrics.py) - one clock, two consumers.
APP_START_TIME = time.monotonic()
