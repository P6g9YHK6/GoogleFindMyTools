#
#  GoogleFindMyTools - A set of tools to interact with the Google Find My API
#  Copyright © 2024 Leon Böttger. All rights reserved.
#

import base64
import hashlib
import json
import logging
import os

import yaml
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger("Auth.token_cache")

SECRETS_FILE = 'auth.yaml'
# Pre-YAML location - _migrate_from_legacy_json() reads this once, then never again.
LEGACY_SECRETS_FILE = 'secrets.json'

# Marks a value in auth.yaml as AES-256-GCM encrypted (see _encrypt/_decrypt
# below) - versioned so a future change to the scheme can tell old and new
# values apart. Anything not carrying this prefix is read back as-is, so
# values written before SECRETS_ENCRYPTION_KEY was ever set (or with it
# unset) keep working without any migration step.
_ENC_PREFIX = "gfmtenc1:"

_warned_unencrypted = False


def _encryption_key() -> bytes | None:
    """Every value in auth.yaml is encrypted with this key when set (any
    string - hashed down to an AES-256 key, so there's no fixed-length/
    encoding requirement on what the user puts in the env var) - see
    _encrypt/_decrypt. Unset or empty means what it always meant: values are
    stored as plain YAML, same as before this existed."""
    raw = os.environ.get("SECRETS_ENCRYPTION_KEY")
    if not raw:
        return None
    return hashlib.sha256(raw.encode()).digest()


def _warn_if_unencrypted():
    global _warned_unencrypted
    if _warned_unencrypted or _encryption_key() is not None:
        return
    _warned_unencrypted = True
    logger.warning(
        "SECRETS_ENCRYPTION_KEY is not set - credentials in %s (OAuth tokens, FCM "
        "credentials, vault keys, ...) are stored in plain text on disk. Set "
        "SECRETS_ENCRYPTION_KEY to encrypt them at rest.",
        _auth_store_path(),
    )


def _encrypt(value):
    """value can be any JSON-able type (a plain string, or fcm_credentials'
    nested dict) - serialized to JSON before encrypting so this isn't just
    for flat strings."""
    key = _encryption_key()
    if key is None:
        return value
    plaintext = json.dumps(value).encode()
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, None)
    return _ENC_PREFIX + base64.b64encode(nonce + ciphertext).decode()


def _decrypt(value):
    key = _encryption_key()
    if key is None or not isinstance(value, str) or not value.startswith(_ENC_PREFIX):
        return value  # not encrypted (no key configured, or predates one being set)
    try:
        blob = base64.b64decode(value[len(_ENC_PREFIX):])
        nonce, ciphertext = blob[:12], blob[12:]
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, None)
        return json.loads(plaintext)
    except (InvalidTag, ValueError):
        # Wrong/rotated SECRETS_ENCRYPTION_KEY, or corrupt data - treat as
        # missing rather than crashing every caller of get_cached_value.
        logger.error("Could not decrypt a value from %s - wrong SECRETS_ENCRYPTION_KEY?", _auth_store_path())
        return None


def get_cached_value_or_set(name: str, generator: callable):

    existing_value = get_cached_value(name)

    if existing_value is not None:
        return existing_value

    value = generator()
    set_cached_value(name, value)
    return value


def get_cached_value(name: str):
    _warn_if_unencrypted()
    value = _decrypt(_load().get(name))
    return value if value else None


def get_cached_values_with_prefix(prefix: str) -> dict:
    """Returns {name: value} for every cached entry whose name starts with
    prefix, e.g. all shared_key_v* entries cached per vault key version by
    KeyBackup/vault_web_api.py."""
    _warn_if_unencrypted()
    return {name: _decrypt(value) for name, value in _load().items() if name.startswith(prefix)}


def clear_all_cached_values():
    """Wipes every cached credential (aas_token, fcm_credentials, shared_key,
    owner_key, username, ...), e.g. for the web UI's "Clear credentials"
    button. Writes an empty object rather than deleting the file, matching
    what get_cached_value/set_cached_value already expect to find."""
    _save({})


def set_cached_value(name: str, value):
    _warn_if_unencrypted()
    data = _load(strict=True)
    data[name] = _encrypt(value)
    _save(data)


def _load(strict: bool = False) -> dict:
    secrets_file = _auth_store_path()
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
    write it straight back out as auth.yaml (encrypting each value if
    SECRETS_ENCRYPTION_KEY is set, same as any other write), and leave the
    old file in place untouched (as a backup, and so a downgrade isn't a
    hard break). Every load after that first migration hits the YAML file
    directly and never looks at the JSON file again."""
    legacy_file = os.path.join(os.path.dirname(_auth_store_path()), LEGACY_SECRETS_FILE)
    if not os.path.exists(legacy_file):
        return None
    with open(legacy_file) as file:
        try:
            data = json.load(file)
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict):
        return None
    encrypted = {name: _encrypt(value) for name, value in data.items()}
    _save(encrypted)
    return data


def _save(data: dict):
    with open(_auth_store_path(), 'w') as file:
        yaml.safe_dump(data, file, sort_keys=False, allow_unicode=True)


def _auth_store_path():
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
