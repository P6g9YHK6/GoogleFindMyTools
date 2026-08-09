"""Docker HEALTHCHECK probe for the web container.

Exits 0 if the app answers /health, 1 otherwise. Written in Python rather
than shelling out to curl since curl isn't installed in this image (see the
Dockerfile's comment on keeping apt packages minimal) and Python already is.
"""

import sys
import urllib.request

try:
    with urllib.request.urlopen("http://localhost:4321/health", timeout=3) as resp:
        sys.exit(0 if resp.status == 200 else 1)
except Exception:
    sys.exit(1)
