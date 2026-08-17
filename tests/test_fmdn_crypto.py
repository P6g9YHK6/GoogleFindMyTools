"""FMDNCrypto/ (EID generation, owner-key derivation, foreign-tracker
encrypt/decrypt) had zero automated coverage before this file - see the code
quality audit. Self-contained: no dependency on the local example_data.json
fixture, uses generated/fixed test vectors instead."""

import hashlib
import hmac
import secrets

import pytest

from FMDNCrypto.eid_generator import ROTATION_PERIOD, calculate_r, generate_eid, get_masked_timestamp
from FMDNCrypto.foreign_tracker_cryptor import decrypt, decrypt_aes_eax, encrypt, encrypt_aes_eax
from FMDNCrypto.key_derivation import FMDNOwnerOperations
from FMDNCrypto.sha import calculate_hmac_sha256, calculate_truncated_sha256


def test_calculate_truncated_sha256_is_8_bytes_and_deterministic():
    key = b"\x01" * 16
    assert calculate_truncated_sha256(key, 0x01) == calculate_truncated_sha256(key, 0x01)
    assert len(calculate_truncated_sha256(key, 0x01)) == 8


def test_calculate_truncated_sha256_differs_per_operation_byte():
    key = b"\x01" * 16
    assert calculate_truncated_sha256(key, 0x01) != calculate_truncated_sha256(key, 0x02)


def test_calculate_hmac_sha256_matches_stdlib():
    key, message = b"secret-key", b"some message"
    expected = hmac.new(key, message, hashlib.sha256).hexdigest()
    assert calculate_hmac_sha256(key, message) == expected


def test_get_masked_timestamp_zeroes_the_low_k_bits():
    # K=10 -> low 10 bits cleared, i.e. rounded down to a multiple of 1024.
    assert get_masked_timestamp(1023, 10) == (0).to_bytes(4, "big")
    assert get_masked_timestamp(1024 + 5, 10) == (1024).to_bytes(4, "big")


def test_calculate_r_is_stable_within_one_rotation_period():
    identity_key = secrets.token_bytes(16)
    assert calculate_r(identity_key, 0) == calculate_r(identity_key, ROTATION_PERIOD - 1)


def test_calculate_r_changes_across_rotation_periods():
    identity_key = secrets.token_bytes(16)
    assert calculate_r(identity_key, 0) != calculate_r(identity_key, ROTATION_PERIOD)


def test_generate_eid_is_20_bytes_and_deterministic():
    identity_key = secrets.token_bytes(16)
    eid = generate_eid(identity_key, 12345)
    assert len(eid) == 20
    assert eid == generate_eid(identity_key, 12345)


def test_generate_eid_differs_for_different_identity_keys():
    a = generate_eid(secrets.token_bytes(16), 0)
    b = generate_eid(secrets.token_bytes(16), 0)
    assert a != b


def test_generate_keys_produces_three_distinct_8_byte_keys():
    ops = FMDNOwnerOperations()
    ops.generate_keys(secrets.token_bytes(20))
    keys = [ops.recovery_key, ops.ringing_key, ops.tracking_key]
    assert all(len(k) == 8 for k in keys)
    assert len(set(keys)) == 3


def test_generate_keys_raises_instead_of_leaving_keys_as_none():
    ops = FMDNOwnerOperations()
    with pytest.raises(TypeError):
        ops.generate_keys(identity_key="not-bytes")
    assert ops.recovery_key is None


def test_encrypt_aes_eax_rejects_a_non_32_byte_key():
    with pytest.raises(ValueError):
        encrypt_aes_eax(b"data", nonce=b"n" * 16, key=b"short")


def test_encrypt_decrypt_aes_eax_round_trips():
    key = secrets.token_bytes(32)
    nonce = secrets.token_bytes(16)
    ciphertext, tag = encrypt_aes_eax(b"hello world", nonce, key)
    assert decrypt_aes_eax(ciphertext, tag, nonce, key) == b"hello world"


def test_foreign_tracker_encrypt_decrypt_round_trips():
    identity_key = secrets.token_bytes(16)
    timestamp = 5 * ROTATION_PERIOD
    eid = generate_eid(identity_key, timestamp)
    message = b"some location payload"

    encrypted_and_tag, sx = encrypt(message, secrets.token_bytes(32), eid)
    decrypted = decrypt(identity_key, encrypted_and_tag, sx, timestamp)

    assert decrypted == message
