import secrets

import pytest

from KeyBackup.cloud_key_decryptor import encrypt_aes_gcm
from ProtoDecoders.DeviceUpdate_pb2 import DeviceRegistration
from SpotApi import identity_key
from SpotApi.CreateBleDevice.config import mcu_fast_pair_model_id
from SpotApi.CreateBleDevice.util import flip_bits

OWNER_KEY = bytes(32)


def _device_registration(encrypted_identity_key: bytes, fast_pair_model_id: str,
                          owner_key_version: int = 1) -> DeviceRegistration:
    device_registration = DeviceRegistration()
    device_registration.fastPairModelId = fast_pair_model_id
    device_registration.encryptedUserSecrets.encryptedIdentityKey = encrypted_identity_key
    device_registration.encryptedUserSecrets.ownerKeyVersion = owner_key_version
    return device_registration


def test_retrieve_identity_key_decrypts_legacy_flipped_device(monkeypatch):
    monkeypatch.setattr(identity_key, "get_owner_key", lambda owner_key_version=-1: OWNER_KEY)

    eik = secrets.token_bytes(32)
    # Same corruption create_ble_device.py's register_esp32() applies by
    # default - every device registered before experimental_official_app_compat
    # existed looks like this.
    encrypted_identity_key = flip_bits(encrypt_aes_gcm(OWNER_KEY, eik), True)
    device_registration = _device_registration(encrypted_identity_key, mcu_fast_pair_model_id)

    assert identity_key.retrieve_identity_key(device_registration) == eik


def test_retrieve_identity_key_decrypts_experimental_unflipped_device(monkeypatch):
    monkeypatch.setattr(identity_key, "get_owner_key", lambda owner_key_version=-1: OWNER_KEY)

    eik = secrets.token_bytes(32)
    # No corruption - what register_esp32(experimental_official_app_compat=True)
    # sends instead. This is the regression case: the old code unconditionally
    # flipped bits back for any is_mcu_tracker() device, which would corrupt
    # this ciphertext instead of decrypting it.
    encrypted_identity_key = encrypt_aes_gcm(OWNER_KEY, eik)
    device_registration = _device_registration(encrypted_identity_key, mcu_fast_pair_model_id)

    assert identity_key.retrieve_identity_key(device_registration) == eik


def test_retrieve_identity_key_still_works_for_real_android_device(monkeypatch):
    monkeypatch.setattr(identity_key, "get_owner_key", lambda owner_key_version=-1: OWNER_KEY)

    eik = secrets.token_bytes(32)
    # A real (non-MCU) device's encryptedIdentityKey is never bit-flipped -
    # is_mcu_tracker() must stay False here so only the raw bytes are tried,
    # same as before this change.
    encrypted_identity_key = encrypt_aes_gcm(OWNER_KEY, eik)
    device_registration = _device_registration(encrypted_identity_key, "some-real-fast-pair-model-id")

    assert identity_key.retrieve_identity_key(device_registration) == eik


def test_retrieve_identity_key_raises_when_neither_variant_decrypts(monkeypatch):
    monkeypatch.setattr(identity_key, "get_owner_key", lambda owner_key_version=-1: OWNER_KEY)
    monkeypatch.setattr(identity_key, "get_cached_values_with_prefix", lambda prefix: {})

    class _FakeOwnerKeyMetadata:
        ownerKeyVersion = 1

    class _FakeE2eeData:
        encryptedOwnerKeyAndMetadata = _FakeOwnerKeyMetadata()

    monkeypatch.setattr(identity_key, "get_eid_info", lambda: _FakeE2eeData())

    # Encrypted with a different owner key entirely - neither the flipped nor
    # the raw variant will ever decrypt with OWNER_KEY.
    other_owner_key = secrets.token_bytes(32)
    eik = secrets.token_bytes(32)
    encrypted_identity_key = flip_bits(encrypt_aes_gcm(other_owner_key, eik), True)
    device_registration = _device_registration(encrypted_identity_key, mcu_fast_pair_model_id,
                                                 owner_key_version=1)

    with pytest.raises(RuntimeError):
        identity_key.retrieve_identity_key(device_registration)


def test_retrieve_identity_key_raises_distinct_message_when_owner_key_was_reset(monkeypatch):
    monkeypatch.setattr(identity_key, "get_owner_key", lambda owner_key_version=-1: OWNER_KEY)
    monkeypatch.setattr(identity_key, "get_cached_values_with_prefix", lambda prefix: {})

    class _FakeOwnerKeyMetadata:
        ownerKeyVersion = 2  # newer than the tracker's own version below

    class _FakeE2eeData:
        encryptedOwnerKeyAndMetadata = _FakeOwnerKeyMetadata()

    monkeypatch.setattr(identity_key, "get_eid_info", lambda: _FakeE2eeData())

    other_owner_key = secrets.token_bytes(32)
    eik = secrets.token_bytes(32)
    encrypted_identity_key = flip_bits(encrypt_aes_gcm(other_owner_key, eik), True)
    device_registration = _device_registration(encrypted_identity_key, mcu_fast_pair_model_id,
                                                 owner_key_version=1)

    with pytest.raises(RuntimeError, match="reset your end-to-end-encrypted"):
        identity_key.retrieve_identity_key(device_registration)
