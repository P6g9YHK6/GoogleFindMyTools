"""Docker HEALTHCHECK probe for the web container.

Exits 0 if the app answers /health, 1 otherwise. Written in Python rather
than shelling out to curl since curl isn't installed in this image (see the
Dockerfile's comment on keeping apt packages minimal) and Python already is.
"""

import pathlib
import ssl
import sys
import urllib.request

# Docker execs this as `python3 docker/web/healthcheck.py`, which puts this
# script's own directory on sys.path[0], not the container's WORKDIR (/app)
# - without this, `from webui import config` below raises ModuleNotFoundError
# and takes the healthcheck itself down. webui/config.py only imports
# os/pathlib, so this stays a cheap import, not a real dependency pull-in.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from webui import config  # noqa: E402


def _scheme_and_context() -> tuple[str, ssl.SSLContext | None]:
    """A local liveness check against a cert this same container may have
    just generated itself, not a real trust decision - same reasoning as
    /health already being exempted from Basic Auth
    (webui/auth_middleware.py). check_hostname must be set False before
    verify_mode=CERT_NONE, or this raises ValueError."""
    if not config.HTTPS_ENABLED:
        return "http", None
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return "https", context


def _check() -> bool:
    scheme, context = _scheme_and_context()
    try:
        with urllib.request.urlopen(f"{scheme}://localhost:4321/health", timeout=3, context=context) as resp:
            return resp.status == 200
    except Exception:
        return False


if __name__ == "__main__":
    sys.exit(0 if _check() else 1)
