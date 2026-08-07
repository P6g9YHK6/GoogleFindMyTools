"""Feeds the System Log page (webui/system_log_store.py) from every logger
app-wide - webui.*, Auth.*, NovaApi.*, everything - by attaching to the root
logger, the same way webui/notify.py's Apprise handler does and for the same
reason: a failure logged from outside the webui.* tree (e.g. Auth.fcm_receiver
crashing) is otherwise invisible to anything only listening on "webui".
"""

import logging

from webui import system_log_store

_NOISY_LOGGERS = {"uvicorn.access"}


class _SystemLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord):
        if record.name in _NOISY_LOGGERS:
            return
        try:
            message = self.format(record)
        except Exception:
            self.handleError(record)
            return
        system_log_store.append(
            level=record.levelname,
            logger_name=record.name,
            message=message,
            when=int(record.created),
        )


def configure_log_capture(level: int = logging.INFO) -> logging.Handler:
    """Installs the system-log capture handler on the root logger, called
    once at app startup (webui/main.py's lifespan). Idempotent like
    webui.notify.configure_apprise_logging(), so it's safe to call again
    without accumulating duplicate handlers/entries.
    """
    root_logger = logging.getLogger()
    for existing in list(root_logger.handlers):
        if isinstance(existing, _SystemLogHandler):
            root_logger.removeHandler(existing)

    handler = _SystemLogHandler(level=level)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root_logger.addHandler(handler)
    return handler
