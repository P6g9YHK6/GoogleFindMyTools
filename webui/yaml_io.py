"""Shared read/write primitives for the small locked YAML config/state files
under webui/ (settings_store.py, device_location_store.py,
forwarders/config_store.py, forwarders/latest_values_store.py) - one
implementation instead of four near-identical copies, and atomic writes.
"""

from pathlib import Path

import yaml


def read_yaml_dict(path: Path) -> tuple[dict, bool]:
    """(data, ok). Missing/empty file -> ({}, True) - a legitimate "nothing
    saved yet" state, not a failure. Unreadable/corrupt/non-mapping file ->
    ({}, False)."""
    if not path.exists():
        return {}, True
    try:
        with path.open() as f:
            data = yaml.safe_load(f)
    except (yaml.YAMLError, OSError):
        return {}, False
    if data is None:
        return {}, True
    if not isinstance(data, dict):
        return {}, False
    return data, True


def write_yaml_dict(path: Path, data: dict) -> None:
    """Atomic write (tempfile + rename) so a crash mid-write can't leave a
    truncated/corrupt file behind."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
    tmp.replace(path)
