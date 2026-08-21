#
#  GoogleFindMyTools - A set of tools to interact with the Google Find My API
#  Copyright © 2024 Leon Böttger. All rights reserved.
#
"""is_mcu_tracker/retrieve_identity_key used to live in
NovaApi/ExecuteAction/LocateTracker/decrypt_locations.py, but both depend
entirely on SpotApi (and KeyBackup/Auth) - nothing NovaApi-specific - while
SpotApi/UploadPrecomputedPublicKeyIds/upload_precomputed_public_key_ids.py
needed to import them back from NovaApi, a real circular package
dependency. Moved here so NovaApi depends on SpotApi (as it already does
elsewhere) and SpotApi never depends back on NovaApi.
"""

import logging

from Auth.token_cache import get_cached_values_with_prefix
from KeyBackup.cloud_key_decryptor import decrypt_eik
from ProtoDecoders.DeviceUpdate_pb2 import DeviceRegistration
from SpotApi.CreateBleDevice.config import mcu_fast_pair_model_id
from SpotApi.CreateBleDevice.util import flip_bits
from SpotApi.GetEidInfoForE2eeDevices.get_eid_info_request import get_eid_info
from SpotApi.GetEidInfoForE2eeDevices.get_owner_key import get_owner_key, get_owner_key_from_wrapped_blob

logger = logging.getLogger(__name__)


# Indicates if the device is a custom microcontroller
def is_mcu_tracker(device_registration: DeviceRegistration) -> bool:
    return device_registration.fastPairModelId == mcu_fast_pair_model_id


def _decrypt_identity_key(owner_key: bytes, encrypted_user_secrets, is_mcu: bool) -> bytes:
    """Tries to decrypt encryptedIdentityKey with owner_key, handling both
    possible states of an MCU tracker's field: bit-flipped (the default at
    registration - see create_ble_device.py's register_esp32(), which
    corrupts it so the official Find My Device app can't decrypt it) or not
    (only possible when registered with the experimental
    experimental_official_app_compat=True flag, which skips that
    corruption). fastPairModelId can't tell the two apart - both use the
    same shared MCU model ID regardless of the flag - so the flipped variant
    (the default, and the only possibility for anything registered before
    that flag existed) is tried first, falling back to the raw bytes as
    received. A wrong guess just fails AES-GCM's tag check (decrypt_eik ->
    decrypt_aes_gcm -> AESGCM.decrypt raises on a bad tag - already the
    fallback-retry mechanism callers of this function rely on for owner-key
    version mismatches), so trying both here is safe: false-positive success
    on a wrong 96-bit tag is cryptographically negligible. Non-MCU trackers
    (real Android/Fast Pair devices, never registered by this project) never
    had this corruption applied, so only the raw bytes are tried for those -
    unchanged from before this flag existed.
    """
    encrypted_identity_key = encrypted_user_secrets.encryptedIdentityKey
    candidates = (
        [flip_bits(encrypted_identity_key, True), encrypted_identity_key]
        if is_mcu else [encrypted_identity_key]
    )
    last_error = None
    for candidate in candidates:
        try:
            return decrypt_eik(owner_key, candidate)
        except Exception as e:
            last_error = e
    raise last_error


def retrieve_identity_key(device_registration: DeviceRegistration) -> bytes:
    is_mcu = is_mcu_tracker(device_registration)
    encrypted_user_secrets = device_registration.encryptedUserSecrets

    try:
        return _decrypt_identity_key(get_owner_key(), encrypted_user_secrets, is_mcu)
    except Exception as e:
        logger.debug("Current owner key didn't decrypt this tracker's identity key (%s), trying next.", e)

    # The account-level "current" owner key (owner_key_version=-1) didn't decrypt
    # this tracker's identity key - retry by asking explicitly for the version the
    # tracker's own data says it needs, instead of trusting whatever "-1" happened
    # to resolve to. An account can have trackers on more than one owner key
    # generation; see SpotApi/GetEidInfoForE2eeDevices/get_owner_key.py.
    needed_version = encrypted_user_secrets.ownerKeyVersion
    try:
        return _decrypt_identity_key(get_owner_key(owner_key_version=needed_version), encrypted_user_secrets, is_mcu)
    except Exception as e:
        logger.debug("Owner key version %s didn't decrypt this tracker's identity key (%s), trying next.",
                      needed_version, e)

    # Last resort: GetEidInfoForE2eeDevices always hands back its own idea of
    # "current" regardless of which version we ask it for (both attempts
    # above confirmed that empirically) - so try every owner-key blob fetched
    # directly from the real Find My Device web app's own API during sign-in
    # instead (see KeyBackup/vault_web_api.py). Each is still encrypted with
    # this account's one stable shared key; verified that unwrapping the
    # "current" version's blob this way reproduces the exact owner key the
    # normal path above already derives, so the same unwrap applied to every
    # other cached version is expected to yield each of those real keys too.
    for name, blob_hex in get_cached_values_with_prefix("encrypted_owner_key_v").items():
        try:
            owner_key = get_owner_key_from_wrapped_blob(bytes.fromhex(blob_hex))
            identity_key = _decrypt_identity_key(owner_key, encrypted_user_secrets, is_mcu)
            logger.info("Decrypted using %s.", name)
            return identity_key
        except Exception:
            continue

    e2eeData = get_eid_info()
    current_owner_key_version = e2eeData.encryptedOwnerKeyAndMetadata.ownerKeyVersion

    if encrypted_user_secrets.ownerKeyVersion < current_owner_key_version:
        message = (
            f"Failed to decrypt E2EE data. This tracker was encrypted with owner key version "
            f"{encrypted_user_secrets.ownerKeyVersion}, but the current owner key version is "
            f"{current_owner_key_version}.\nThis happens if you reset your end-to-end-encrypted "
            f"data in the past.\nThe tracker cannot be decrypted anymore, and it is recommended "
            f"to remove it in the Find My Device app."
        )
    else:
        tried_versions = ", ".join(sorted(get_cached_values_with_prefix("encrypted_owner_key_v").keys())) or "none cached"
        message = (
            f"Failed to decrypt identity key encrypted with owner key version "
            f"{encrypted_user_secrets.ownerKeyVersion}, current owner key version is "
            f"{current_owner_key_version}. Also retried by explicitly requesting owner key "
            f"version {needed_version}, and by trying every vault key version fetched from the "
            f"Find My Device web app during sign-in ({tried_versions}) - all failed to decrypt."
            f"\nThis may happen if the cached owner key is stale (e.g. after re-doing the Google "
            f"sign-in). To resolve this issue, clear the 'owner_key' entry from "
            f"'Auth/secrets.json' so it gets re-derived, or delete the whole file to sign in "
            f"again from scratch."
        )
    logger.error(message)
    # exit(1) here would raise SystemExit, which is fine for the CLI scripts this
    # was originally written for but fatal when called from a web request thread
    # (asyncio.to_thread) - it doesn't stop the server, just crashes that one
    # request with a bare "Internal Server Error" and no indication why. Raise a
    # normal exception instead so callers (e.g. the web UI's locate endpoint) can
    # show `message` to the user.
    raise RuntimeError(message)
