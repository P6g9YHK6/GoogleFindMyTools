"""Shared read/write primitives for the small tab-separated bounded-log files
under webui/ (system_log_store.py, forwarders/log_store.py) - one
implementation of the read-all/write-all mechanics instead of two, and
atomic writes.
"""

from collections.abc import Callable
from pathlib import Path


def read_lines(path: Path, parse_line: Callable[[str], dict | None]) -> list[dict]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        return []
    entries = []
    try:
        with path.open() as f:
            for line in f:
                line = line.rstrip("\n")
                if not line:
                    continue
                parsed = parse_line(line)
                if parsed is not None:
                    entries.append(parsed)
    except OSError:
        return []
    return entries


def write_lines(path: Path, entries: list[dict], format_line: Callable[[dict], str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w") as f:
        for entry in entries:
            f.write(format_line(entry) + "\n")
    tmp.replace(path)
