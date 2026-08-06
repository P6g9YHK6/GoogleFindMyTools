import json
import threading
import time

from webui import config

_lock = threading.Lock()


def _empty():
    return {"entries": []}


def _level(status: str) -> str:
    if status == "ok":
        return "ok"
    if status.startswith("error"):
        return "error"
    return "skipped"  # e.g. a semantic-only location, or a disabled destination


def load() -> dict:
    with _lock:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        if not config.FORWARD_LOG_PATH.exists():
            return _empty()
        try:
            with open(config.FORWARD_LOG_PATH, "r") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return _empty()
        data.setdefault("entries", [])
        return data


def save(data: dict):
    with _lock:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(config.FORWARD_LOG_PATH, "w") as f:
            json.dump(data, f, indent=2)


def append(canonic_id: str, device_name: str, endpoint_type: str, target: str, status: str):
    data = load()
    data["entries"].append({
        "time": int(time.time()),
        "canonic_id": canonic_id,
        "device_name": device_name,
        "endpoint_type": endpoint_type,
        "target": target,
        "status": status,
        "level": _level(status),
    })
    # Keep the log file bounded instead of growing it forever.
    if len(data["entries"]) > config.FORWARD_LOG_MAX_ENTRIES:
        data["entries"] = data["entries"][-config.FORWARD_LOG_MAX_ENTRIES:]
    save(data)


def recent_entries(limit: int = 500) -> list[dict]:
    """Newest first."""
    entries = load()["entries"]
    return list(reversed(entries))[:limit]
