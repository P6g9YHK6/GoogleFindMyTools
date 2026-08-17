import json
import re
import threading
import time

from webui import config
from webui.line_log_io import read_lines, write_lines

_lock = threading.Lock()

# Tabs/newlines would break the one-entry-per-line format below - none of
# these fields (a device name, a forwarder URL, an exception message) are
# ever expected to contain either, so collapsing them to a space is a
# non-issue in practice.
_SANITIZE_RE = re.compile(r"[\t\r\n]+")


def _level(status: str) -> str:
    if status == "ok":
        return "ok"
    if status.startswith("error"):
        return "error"
    return "skipped"  # e.g. a semantic-only location, or a disabled destination


def _sanitize(value: str) -> str:
    return _SANITIZE_RE.sub(" ", str(value))


def _format_line(entry: dict) -> str:
    return "\t".join([
        str(entry["time"]),
        _sanitize(entry["canonic_id"]),
        _sanitize(entry["device_name"]),
        _sanitize(entry["endpoint_type"]),
        _sanitize(entry["target"]),
        _sanitize(entry["status"]),
        _sanitize(entry.get("payload", "")),
        _sanitize(entry.get("response", "")),
    ])


def _parse_line(line: str) -> dict | None:
    parts = line.split("\t", 7)
    if len(parts) == 6:
        parts.append("")  # a line written before the payload column existed
    if len(parts) == 7:
        parts.append("")  # a line written before the response column existed
    if len(parts) != 8:
        return None
    time_s, canonic_id, device_name, endpoint_type, target, status, payload, response = parts
    try:
        entry_time = int(time_s)
    except ValueError:
        return None
    return {
        "time": entry_time,
        "canonic_id": canonic_id,
        "device_name": device_name,
        "endpoint_type": endpoint_type,
        "target": target,
        "status": status,
        "payload": payload,
        "response": response,
        "level": _level(status),
    }


def _migrate_from_legacy_json() -> list[dict] | None:
    """One-time upgrade path from the pre-.log forward_log.json - read it
    once, write it straight back out as forward.log, and leave the old file
    in place untouched (as a backup). Every read after that first migration
    reads the .log file directly and never looks at the JSON file again."""
    if not config.FORWARD_LOG_LEGACY_JSON_PATH.exists():
        return None
    try:
        with open(config.FORWARD_LOG_LEGACY_JSON_PATH) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return None
    _write_all(entries)
    return entries


def _read_all() -> list[dict]:
    if not config.FORWARD_LOG_PATH.exists():
        return _migrate_from_legacy_json() or []
    return read_lines(config.FORWARD_LOG_PATH, _parse_line)


def _write_all(entries: list[dict]):
    write_lines(config.FORWARD_LOG_PATH, entries, _format_line)


def append(
    canonic_id: str, device_name: str, endpoint_type: str, target: str, status: str,
    payload: str = "", response: str = "",
):
    with _lock:
        entries = _read_all()
        entries.append({
            "time": int(time.time()),
            "canonic_id": canonic_id,
            "device_name": device_name,
            "endpoint_type": endpoint_type,
            "target": target,
            "status": status,
            "payload": payload,
            "response": response,
        })
        # Keep the log file bounded instead of growing it forever.
        if len(entries) > config.FORWARD_LOG_MAX_ENTRIES:
            entries = entries[-config.FORWARD_LOG_MAX_ENTRIES:]
        _write_all(entries)


def recent_entries(limit: int = 500) -> list[dict]:
    """Newest first."""
    with _lock:
        entries = _read_all()
    return list(reversed(entries))[:limit]
