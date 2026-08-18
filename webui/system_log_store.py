"""Bounded storage for the Logs page's system entries - every INFO-or-above
log record from anywhere in the app (see webui/log_capture.py), as opposed to
webui/forwarders/log_store.py which only ever holds forwarding attempts.
Same plain-line-per-entry approach as that module (see it for why: no JSON/
YAML, just tab-separated fields parsed back on read).
"""

import re
import threading

from webui import config
from webui.line_log_io import append_line, read_lines, write_lines

_lock = threading.Lock()

_SANITIZE_RE = re.compile(r"[\t\r\n]+")


def _sanitize(value: str) -> str:
    return _SANITIZE_RE.sub(" ", str(value))


def _format_line(entry: dict) -> str:
    return "\t".join([
        str(entry["time"]),
        _sanitize(entry["level"]),
        _sanitize(entry["logger"]),
        _sanitize(entry["message"]),
    ])


def _parse_line(line: str) -> dict | None:
    parts = line.split("\t", 3)
    if len(parts) != 4:
        return None
    time_s, level, logger_name, message = parts
    try:
        entry_time = int(time_s)
    except ValueError:
        return None
    return {"time": entry_time, "level": level, "logger": logger_name, "message": message}


def _read_all() -> list[dict]:
    return read_lines(config.SYSTEM_LOG_PATH, _parse_line)


def _write_all(entries: list[dict]):
    write_lines(config.SYSTEM_LOG_PATH, entries, _format_line)


def append(level: str, logger_name: str, message: str, when: int):
    with _lock:
        entry = {"time": when, "level": level, "logger": logger_name, "message": message}
        append_line(config.SYSTEM_LOG_PATH, entry, _format_line, _parse_line, config.SYSTEM_LOG_MAX_ENTRIES)


def recent_entries(limit: int = 500) -> list[dict]:
    """Newest first."""
    with _lock:
        entries = _read_all()
    return list(reversed(entries))[:limit]
