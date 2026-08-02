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

# If set, the whole web UI (including the WebSocket) requires this password
# via HTTP Basic Auth (any username). Unset by default - see README.
WEBUI_PASSWORD = os.environ.get("WEBUI_PASSWORD")

DATA_DIR = pathlib.Path(__file__).parent / "data"
FORWARDING_CONFIG_PATH = DATA_DIR / "forwarding_config.json"
