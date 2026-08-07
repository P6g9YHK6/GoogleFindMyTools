import base64
import binascii

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from Auth.firebase_messaging.fcmpushclient import FcmPushClient


def _unpadded_b64url(data: bytes) -> str:
    """Real push messages commonly send base64url values with their padding
    stripped, per RFC 4648 §5 / how most web-push implementations format
    these headers."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def test_decrypt_raw_data_tolerates_unpadded_crypto_key_and_salt():
    """Regression test: _decrypt_raw_data used to call urlsafe_b64decode on
    crypto_key_str/salt_str with no padding at all, unlike the private
    key/secret decodes two lines below which already pad defensively - any
    push message with unpadded headers (common) raised
    binascii.Error("Incorrect padding") before ever reaching real
    decryption, which crashed and terminated the whole FcmPushClient
    listener (see Auth/fcm_receiver.py's _listen loop)."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    der = private_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    credentials = {
        "keys": {
            "private": _unpadded_b64url(der),
            "secret": _unpadded_b64url(b"0" * 16),
        },
    }
    crypto_key_str = _unpadded_b64url(b"\x04" + b"0" * 64)  # uncompressed EC point shape
    salt_str = _unpadded_b64url(b"0" * 16)

    # The fake key/salt/ciphertext mean real decryption still can't succeed -
    # this only asserts we get past the padding step that used to crash
    # immediately, into whatever (unrelated) error the bogus crypto data
    # produces further down.
    with pytest.raises(Exception) as exc_info:
        FcmPushClient._decrypt_raw_data(credentials, crypto_key_str, salt_str, b"fake-encrypted-data")
    assert not isinstance(exc_info.value, binascii.Error)
