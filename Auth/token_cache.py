#
#  GoogleFindMyTools - A set of tools to interact with the Google Find My API
#  Copyright © 2024 Leon Böttger. All rights reserved.
#

import json
import os

import yaml

SECRETS_FILE = 'auth.yaml'
# Pre-YAML location - _migrate_from_legacy_json() reads this once, then never again.
LEGACY_SECRETS_FILE = 'secrets.json'

def get_cached_value_or_set(name: str, generator: callable):

    existing_value = get_cached_value(name)

    if existing_value is not None:
        return existing_value

    value = generator()
    set_cached_value(name, value)
    return value


def get_cached_value(name: str):
    value = _load().get(name)
    return value if value else None


def get_cached_values_with_prefix(prefix: str) -> dict:
    """Returns {name: value} for every cached entry whose name starts with
    prefix, e.g. all shared_key_v* entries cached per vault key version by
    KeyBackup/vault_web_api.py."""
    return {name: value for name, value in _load().items() if name.startswith(prefix)}


def clear_all_cached_values():
    """Wipes every cached credential (aas_token, fcm_credentials, shared_key,
    owner_key, username, ...), e.g. for the web UI's "Clear credentials"
    button. Writes an empty object rather than deleting the file, matching
    what get_cached_value/set_cached_value already expect to find."""
    _save({})


def set_cached_value(name: str, value: str):
    data = _load(strict=True)
    data[name] = value
    _save(data)


def _load(strict: bool = False) -> dict:
    secrets_file = _get_secrets_file()
    if os.path.exists(secrets_file):
        with open(secrets_file) as file:
            try:
                data = yaml.safe_load(file)
            except yaml.YAMLError:
                if strict:
                    # A write is about to happen - refuse rather than silently
                    # start from {} and clobber whatever's actually in there.
                    raise Exception("Could not read secrets file. Aborting.") from None
                return {}
        return data if isinstance(data, dict) else {}
    return _migrate_from_legacy_json() or {}


def _migrate_from_legacy_json() -> dict | None:
    """One-time upgrade path from the pre-YAML secrets.json - read it once,
    write it straight back out as auth.yaml, and leave the old file in place
    untouched (as a backup, and so a downgrade isn't a hard break). Every
    load after that first migration hits the YAML file directly and never
    looks at the JSON file again."""
    legacy_file = os.path.join(os.path.dirname(_get_secrets_file()), LEGACY_SECRETS_FILE)
    if not os.path.exists(legacy_file):
        return None
    with open(legacy_file) as file:
        try:
            data = json.load(file)
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict):
        return None
    _save(data)
    return data


def _save(data: dict):
    with open(_get_secrets_file(), 'w') as file:
        yaml.safe_dump(data, file, sort_keys=False, allow_unicode=True)


def _get_secrets_file():
    # Lets the secrets file live in a mounted directory (e.g. in Docker)
    # instead of always sitting next to this script. GFMT_SECRETS_DIR is kept
    # for backward compatibility with existing deployments that set it
    # explicitly (auth data in its own directory) - a fresh setup only needs
    # GFMT_DATA_DIR, so auth.yaml lands as a flat file alongside
    # config.yaml/forwarding.yaml/forward.log in one directory, no subfolders.
    secrets_dir = os.environ.get("GFMT_SECRETS_DIR") or os.environ.get("GFMT_DATA_DIR")
    if secrets_dir:
        os.makedirs(secrets_dir, exist_ok=True)
        return os.path.join(secrets_dir, SECRETS_FILE)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(script_dir, SECRETS_FILE)
