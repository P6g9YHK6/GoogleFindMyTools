#
#  GoogleFindMyTools - A set of tools to interact with the Google Find My API
#  Copyright © 2024 Leon Böttger. All rights reserved.
#
"""Captures the browser's Google web-session cookies (SAPISID and friends)
during the existing sign-in flow, for Auth/live_device_info.py's on-demand
queries to Google's real-time "punctual" push channel - a cookie-based auth
scheme, entirely separate from the OAuth tokens the rest of this project
uses. Only runs when ENABLE_LIVE_DEVICE_INFO is set; a plain sign-in never
touches this. Best-effort: any failure here is logged and swallowed, never
allowed to fail the sign-in flow itself.
"""

import logging
import os

from Auth.token_cache import set_cached_value

logger = logging.getLogger("Auth.web_session")

ENABLE_LIVE_DEVICE_INFO = os.environ.get("ENABLE_LIVE_DEVICE_INFO", "0") == "1"


def capture_web_session_cookies(driver):
    if not ENABLE_LIVE_DEVICE_INFO:
        return
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
