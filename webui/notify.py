"""Optional Apprise-backed failure notifications.

Entirely opt-in: with APPRISE_URLS unset, configure_apprise_logging() is a
no-op and nothing is ever sent. Set it (see https://github.com/caronc/apprise
for the URL format - Discord, Telegram, email, ntfy, dozens more) and every
logger anywhere in the process - webui.*, Auth.*, NovaApi.*, third-party
libraries, all of it - gets forwarded automatically, since this attaches to
the root logger (see _TARGET_LOGGER below) that everything propagates up to
by default. (This used to attach to "webui" only, which missed real failures
logged from outside that tree - e.g. Auth.fcm_receiver's push-client crashes
- until a locate had been silently failing for hours with nothing to show
for it.) Nothing here needs updating as new failure points get added
elsewhere, in any module.
"""

import logging
import os
import re
import threading

import apprise

logger = logging.getLogger(__name__)

_TARGET_LOGGER = ""  # root
_DEFAULT_LEVEL = "WARNING"


class _AppriseLogHandler(logging.Handler):
    """Sends each qualifying log record through Apprise on a background
    thread. Apprise's notify() does real (blocking) network I/O, and
    logging.Handler.emit() runs synchronously wherever the triggering log
    call happened - often inside the asyncio event loop itself (see
    webui/scheduler.py's poll loop) - so calling it inline would stall every
    device's polling for however long the webhook/email/etc. takes.
    """

    def __init__(self, apprise_obj: apprise.Apprise, level: int):
        super().__init__(level=level)
        self._apprise = apprise_obj

    def emit(self, record: logging.LogRecord):
        try:
            title = f"GoogleFindMyToolsWebUi: {record.levelname}"
            body = self.format(record)
        except Exception:
            self.handleError(record)
            return
        threading.Thread(target=self._apprise.notify, kwargs={"title": title, "body": body}, daemon=True).start()


def configure_apprise_logging(env: dict | None = None) -> logging.Handler | None:
    """Wires up Apprise from APPRISE_URLS (comma/newline-separated) and
    APPRISE_NOTIFY_LEVEL (a standard logging level name, default WARNING -
    a plain config knob rather than a hardcoded idea of which failures
    "count"). Called once at app startup (webui/main.py's lifespan) and
    again every time the Config page saves new settings - idempotent, since
    it first removes any handler a previous call installed, so it never
    accumulates duplicate handlers (and duplicate notifications) across
    repeated calls. Returns the newly installed handler, or None if
    APPRISE_URLS isn't set.
    """
    env = os.environ if env is None else env
    target_logger = logging.getLogger(_TARGET_LOGGER)
    for existing in list(target_logger.handlers):
        if isinstance(existing, _AppriseLogHandler):
            target_logger.removeHandler(existing)

    urls_raw = (env.get("APPRISE_URLS") or "").strip()
    if not urls_raw:
        return None

    apprise_obj = apprise.Apprise()
    for url in re.split(r"[,\n]+", urls_raw):
        url = url.strip()
        if url and not apprise_obj.add(url):
            logger.warning("Apprise rejected this URL (check its format against the apprise docs): %s", url)

    level_name = (env.get("APPRISE_NOTIFY_LEVEL") or _DEFAULT_LEVEL).strip().upper()
    level = getattr(logging, level_name, None)
    if not isinstance(level, int):
        logger.warning("Unknown APPRISE_NOTIFY_LEVEL %r, defaulting to %s", level_name, _DEFAULT_LEVEL)
        level = logging.WARNING

    handler = _AppriseLogHandler(apprise_obj, level)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logging.getLogger(_TARGET_LOGGER).addHandler(handler)
    return handler
