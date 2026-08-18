"""KeyBackup/ had zero automated coverage before this file - see the code
quality audit. Scoped to the pure-logic pieces (cloud_key_decryptor.py,
lskf_hasher.py, response_parser.py, shared_key_request.py); shared_key_flow.py/
vault_web_api.py/shared_key_retrieval.py drive a live Selenium browser flow
and aren't unit-testable without one.

Real Google vault sample data isn't in this repo (example_data.json is a
local, untracked fixture) - these round-trip each decrypt_* function against
data this file encrypts itself with the matching forward primitive, rather
than against real captured values.
"""

import secrets

import pytest
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from KeyBackup.cloud_key_decryptor import (
    P256_HKDF_AES_GCM,
    SECUREBOX,
    SHARED_HKDF_AES_GCM,
    VERSION,
    decrypt_account_key,
    decrypt_aes_cbc_no_padding,
    decrypt_aes_gcm,
    decrypt_aes_gcm_with_derived_key,
    decrypt_application_key,
    decrypt_eik,
    decrypt_owner_key,
    decrypt_recovery_key,
    decrypt_security_domain_key,
    decrypt_shared_key,
    derive_key_using_hkdf_sha256,
    derive_shared_secret,
    encrypt_aes_gcm,
)
from KeyBackup.lskf_hasher import ascii_to_bytes, get_lskf_hash
from KeyBackup.response_parser import get_fmdn_shared_key
from KeyBackup.shared_key_request import get_security_domain_request_url

# --- lskf_hasher.py ---


def test_ascii_to_bytes():
    assert ascii_to_bytes("1234") == b"1234"


def test_get_lskf_hash_is_deterministic_and_32_bytes():
    salt = secrets.token_bytes(16)
    assert get_lskf_hash("1234", salt) == get_lskf_hash("1234", salt)
    assert len(get_lskf_hash("1234", salt)) == 32


def test_get_lskf_hash_differs_for_a_different_pin_or_salt():
    salt = secrets.token_bytes(16)
    assert get_lskf_hash("1234", salt) != get_lskf_hash("4321", salt)
    assert get_lskf_hash("1234", salt) != get_lskf_hash("1234", secrets.token_bytes(16))


# --- cloud_key_decryptor.py ---


def test_derive_key_using_hkdf_sha256_is_deterministic_and_16_bytes():
    key = derive_key_using_hkdf_sha256(b"input", b"salt", b"info")
    assert key == derive_key_using_hkdf_sha256(b"input", b"salt", b"info")
    assert len(key) == 16


def test_encrypt_decrypt_aes_gcm_round_trips():
    key = secrets.token_bytes(16)
    encrypted = encrypt_aes_gcm(key, b"plaintext", b"aad")
    assert decrypt_aes_gcm(key, encrypted, b"aad") == b"plaintext"


def test_decrypt_aes_gcm_rejects_the_wrong_key():
    encrypted = encrypt_aes_gcm(secrets.token_bytes(16), b"plaintext")
    with pytest.raises(Exception):
        decrypt_aes_gcm(secrets.token_bytes(16), encrypted)


def test_decrypt_aes_cbc_no_padding_round_trips():
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    key = secrets.token_bytes(16)
    iv = secrets.token_bytes(16)
    plaintext = secrets.token_bytes(32)  # a whole number of AES blocks - no padding needed
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend()).encryptor()
    ciphertext = encryptor.update(plaintext) + encryptor.finalize()

    assert decrypt_aes_cbc_no_padding(key, iv + ciphertext) == plaintext


def test_decrypt_aes_gcm_with_derived_key_rejects_the_wrong_version():
    with pytest.raises(ValueError):
        decrypt_aes_gcm_with_derived_key(b"\x00\x00" + b"garbage", secrets.token_bytes(16), b"info")


def test_derive_shared_secret_matches_from_both_directions():
    """ECDH: (a_priv, b_pub) and (b_priv, a_pub) must derive the same secret."""
    a = ec.generate_private_key(ec.SECP256R1(), default_backend())
    b = ec.generate_private_key(ec.SECP256R1(), default_backend())
    a_priv_bytes = a.private_numbers().private_value.to_bytes(32, "big")
    b_priv_bytes = b.private_numbers().private_value.to_bytes(32, "big")
    a_pub_bytes = a.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    b_pub_bytes = b.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)

    assert derive_shared_secret(a_priv_bytes, b_pub_bytes) == derive_shared_secret(b_priv_bytes, a_pub_bytes)


def test_decrypt_shared_key_round_trips_via_ecdh():
    """decrypt_shared_key is the one step that derives its key from an
    embedded ephemeral public key (see decrypt_aes_gcm_with_derived_key's
    derive_with_public_key path) rather than a plain shared secret."""
    receiver = ec.generate_private_key(ec.SECP256R1(), default_backend())
    receiver_priv_bytes = receiver.private_numbers().private_value.to_bytes(32, "big")
    sender = ec.generate_private_key(ec.SECP256R1(), default_backend())
    sender_pub_bytes = sender.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)

    shared_secret = sender.exchange(ec.ECDH(), receiver.public_key())
    derived = derive_key_using_hkdf_sha256(shared_secret, SECUREBOX + VERSION, P256_HKDF_AES_GCM)

    shared_key = secrets.token_bytes(16)
    encrypted_shared_key = VERSION + sender_pub_bytes + encrypt_aes_gcm(derived, shared_key, ascii_to_bytes("V1 shared_key"))

    assert decrypt_shared_key(receiver_priv_bytes, encrypted_shared_key) == shared_key


def test_full_key_chain_round_trips_with_synthetic_data():
    """decrypt_recovery_key -> decrypt_application_key -> decrypt_security_domain_key
    -> decrypt_owner_key -> decrypt_eik/decrypt_account_key - each one's forward
    (encrypt) side, built with the same derived key the real decrypt would
    compute, so a real Google vault response isn't needed to prove the chain
    is wired correctly."""
    lskf_hash = secrets.token_bytes(32)
    recovery_key = secrets.token_bytes(16)
    application_key = secrets.token_bytes(16)
    security_domain_key = secrets.token_bytes(16)
    owner_key = secrets.token_bytes(16)

    # HKDF's "info" is always SHARED_HKDF_AES_GCM/P256_HKDF_AES_GCM (which
    # derive_with_public_key path was taken) - a completely separate string
    # from the AES-GCM "additional_data", which is the specific key_type
    # string each decrypt_* function passes (e.g. "V1 locally_encrypted_
    # recovery_key"). Both have to match on the encrypt side here.
    recovery_key_aad = ascii_to_bytes("V1 locally_encrypted_recovery_key")
    derived = derive_key_using_hkdf_sha256(lskf_hash, SECUREBOX + VERSION, SHARED_HKDF_AES_GCM)
    encrypted_recovery_key = VERSION + encrypt_aes_gcm(derived, recovery_key, recovery_key_aad)
    assert decrypt_recovery_key(lskf_hash, encrypted_recovery_key) == recovery_key

    application_key_aad = ascii_to_bytes("V1 encrypted_application_key")
    derived = derive_key_using_hkdf_sha256(recovery_key, SECUREBOX + VERSION, SHARED_HKDF_AES_GCM)
    encrypted_application_key = VERSION + encrypt_aes_gcm(derived, application_key, application_key_aad)
    assert decrypt_application_key(recovery_key, encrypted_application_key) == application_key

    encrypted_security_domain_key = encrypt_aes_gcm(application_key, security_domain_key)
    assert decrypt_security_domain_key(application_key, encrypted_security_domain_key) == security_domain_key

    encrypted_owner_key = encrypt_aes_gcm(security_domain_key, owner_key)
    # decrypt_owner_key takes the *shared* key, not the security domain key -
    # reuse security_domain_key as a stand-in shared key here since only the
    # plain-AES-GCM wiring is under test, not the ECDH step (see
    # test_decrypt_shared_key_round_trips_via_ecdh for that).
    assert decrypt_owner_key(security_domain_key, encrypted_owner_key) == owner_key

    # decrypt_eik/decrypt_account_key dispatch on the encrypted blob's total
    # length (CBC-no-padding path vs. GCM path - see cloud_key_decryptor.py).
    # EIK is a 32-byte value either way (CBC total 48 = 16 iv + 32 ciphertext,
    # GCM total 60 = 12 iv + 32 ciphertext + 16 tag); the account key is
    # 16 bytes either way (CBC total 32, GCM total 44).
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    def cbc_encrypt(key: bytes, plaintext: bytes) -> bytes:
        iv = secrets.token_bytes(16)
        encryptor = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend()).encryptor()
        return iv + encryptor.update(plaintext) + encryptor.finalize()

    eik = secrets.token_bytes(32)
    assert decrypt_eik(owner_key, cbc_encrypt(owner_key, eik)) == eik  # 48-byte CBC path
    assert decrypt_eik(owner_key, encrypt_aes_gcm(owner_key, eik)) == eik  # 60-byte GCM path

    account_key = secrets.token_bytes(16)
    assert decrypt_account_key(owner_key, cbc_encrypt(owner_key, account_key)) == account_key  # 32-byte CBC path
    assert decrypt_account_key(owner_key, encrypt_aes_gcm(owner_key, account_key)) == account_key  # 44-byte GCM path


def test_decrypt_eik_rejects_an_invalid_length():
    with pytest.raises(ValueError):
        decrypt_eik(secrets.token_bytes(16), b"too short")


def test_decrypt_account_key_rejects_an_invalid_length():
    with pytest.raises(ValueError):
        decrypt_account_key(secrets.token_bytes(16), b"too short")


# --- response_parser.py ---


def test_get_fmdn_shared_key_picks_the_newest_epoch():
    import json

    vault_keys = json.dumps({
        "finder_hw": [
            {"epoch": "1", "key": {"0": 1, "1": 2}},
            {"epoch": "3", "key": {"0": 9, "1": 9}},
            {"epoch": "2", "key": {"0": 3, "1": 4}},
        ],
    })
    assert get_fmdn_shared_key(vault_keys) == bytearray([9, 9])


def test_get_fmdn_shared_key_raises_when_nothing_usable_is_present():
    import json

    with pytest.raises(Exception):
        get_fmdn_shared_key(json.dumps({"finder_hw": []}))
    with pytest.raises(Exception):
        get_fmdn_shared_key(json.dumps({"other_key": "irrelevant"}))


# --- shared_key_request.py ---


def test_get_security_domain_request_url_is_a_finder_hw_unlock_url():
    url = get_security_domain_request_url()
    assert url.startswith("https://accounts.google.com/encryption/unlock/android?kdi=")
    # A fresh call embeds a different random sessionId each time.
    assert url != get_security_domain_request_url()
