#
#  GoogleFindMyTools - A set of tools to interact with the Google Find My API
#  Copyright © 2024 Leon Böttger. All rights reserved.
#
"""Captures the browser's Google web-session cookies (SAPISID and friends)
during the existing sign-in flow, for Auth/live_device_info.py's on-demand
queries to Google's real-time "punctual" push channel - a cookie-based auth
scheme, entirely separate from the OAuth tokens the rest of this project
uses. Always runs as part of sign-in (no separate feature flag - the actual
query only ever happens when explicitly requested, either by whoever calls
Auth/live_device_info.py's open_watch() directly, or via a device
endpoint's "fetch_live_info" toggle in the web UI). Best-effort: any
failure here is logged and swallowed, never allowed to fail the sign-in
flow itself.
"""

import logging

from Auth.token_cache import set_cached_value

logger = logging.getLogger("Auth.web_session")


def capture_web_session_cookies(driver):
    try:
        cookies = [
            {"name": c["name"], "value": c["value"], "domain": c.get("domain"), "path": c.get("path")}
            for c in driver.get_cookies()
            if c.get("name") and c.get("value") is not None
        ]
        if not cookies:
            logger.warning("No cookies found on the signed-in browser session - live device info will stay unavailable")
            return
        set_cached_value("web_session_cookies", cookies)
        logger.info("Captured %d web session cookie(s) for live device info", len(cookies))
    except Exception:
        logger.exception("Failed to capture web session cookies (non-fatal, live device info will stay unavailable)")
