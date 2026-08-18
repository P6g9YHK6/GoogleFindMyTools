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


# How many entries past max_entries a file is allowed to grow before
# append_line() pays for a full read+cap+rewrite - amortizes that cost
# across many appends instead of paying it on every single one.
_COMPACT_SLACK = 200

# Cached line count per path, so append_line() doesn't need to re-read the
# whole file just to know how close it is to needing compaction. Keyed by
# path (not a single scalar) so tests that repoint the same store at a fresh
# tmp_path per test don't inherit a stale count from a previous test's file.
_counts: dict[Path, int] = {}


def append_line(
    path: Path, entry: dict, format_line: Callable[[dict], str],
    parse_line: Callable[[str], dict | None], max_entries: int,
) -> None:
    """True O(1) append (mode "a") instead of the read-all/cap/rewrite-all
    every log append used to pay for. Only actually rewrites the file once
    every _COMPACT_SLACK entries past max_entries, not on every call."""
    path.parent.mkdir(parents=True, exist_ok=True)
    count = _counts.get(path)
    if count is None:
        count = len(read_lines(path, parse_line))
    with path.open("a") as f:
        f.write(format_line(entry) + "\n")
    count += 1
    if count > max_entries + _COMPACT_SLACK:
        entries = read_lines(path, parse_line)[-max_entries:]
        write_lines(path, entries, format_line)
        count = len(entries)
    _counts[path] = count
