import os
import pathlib

BROWSER_AGENT_URL = os.environ.get("BROWSER_AGENT_URL", "http://browser:8001")
# Internal-only: the web container proxies noVNC through its own origin (see
# webui/routers/vnc_proxy.py) so the embedded Chrome view is served as part
# of the web UI itself, not a separately exposed port/origin.
BROWSER_NOVNC_URL = os.environ.get("BROWSER_NOVNC_URL", "http://browser:6901")
WEBUI_PORT = int(os.environ.get("WEBUI_PORT", "4321"))
DEFAULT_POLL_INTERVAL_S = int(os.environ.get("DEFAULT_POLL_INTERVAL_S", "300"))
LOCATE_CONCURRENCY = int(os.environ.get("LOCATE_CONCURRENCY", "5"))
LOCATE_TIMEOUT_S = int(os.environ.get("LOCATE_TIMEOUT_S", "60"))

# If set, the whole web UI (including the WebSocket) requires this password
# via HTTP Basic Auth (any username). Unset by default - see README.
WEBUI_PASSWORD = os.environ.get("WEBUI_PASSWORD")

DATA_DIR = pathlib.Path(__file__).parent / "data"
FORWARDING_CONFIG_PATH = DATA_DIR / "forwarding_config.json"
