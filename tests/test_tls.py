import datetime
import ipaddress
import os
import stat

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from webui import config, tls


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "TLS_CERT_PATH", tmp_path / "tls_cert.pem")
    monkeypatch.setattr(config, "TLS_KEY_PATH", tmp_path / "tls_key.pem")
    monkeypatch.setattr(config, "GFMT_TLS_CERT_PATH", None)
    monkeypatch.setattr(config, "GFMT_TLS_KEY_PATH", None)
    monkeypatch.setattr(config, "GFMT_TLS_SAN", None)


def test_ensure_cert_generates_a_valid_self_signed_cert(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)

    cert_path, key_path = tls.ensure_cert()

    with open(cert_path, "rb") as f:
        cert = x509.load_pem_x509_certificate(f.read())

    cn = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
    assert cn == "GoogleFindMyTools"

    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert "localhost" in san.get_values_for_type(x509.DNSName)
    ips = san.get_values_for_type(x509.IPAddress)
    assert ipaddress.ip_address("127.0.0.1") in ips
    assert ipaddress.ip_address("::1") in ips

    basic_constraints = cert.extensions.get_extension_for_class(x509.BasicConstraints).value
    assert basic_constraints.ca is False

    eku = cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    assert ExtendedKeyUsageOID.SERVER_AUTH in eku

    with open(key_path, "rb") as f:
        key = serialization.load_pem_private_key(f.read(), password=None)
    assert isinstance(key.curve, ec.SECP256R1)


def test_ensure_cert_sets_restrictive_permissions_on_the_key(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)

    _, key_path = tls.ensure_cert()
    mode = stat.S_IMODE(os.stat(key_path).st_mode)
    assert mode == 0o600


def test_ensure_cert_reuses_a_still_valid_cert(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)

    cert_path, key_path = tls.ensure_cert()
    with open(cert_path, "rb") as f:
        first_cert_bytes = f.read()

    cert_path_2, key_path_2 = tls.ensure_cert()
    assert (cert_path_2, key_path_2) == (cert_path, key_path)
    with open(cert_path, "rb") as f:
        assert f.read() == first_cert_bytes  # not rewritten


def test_ensure_cert_regenerates_an_expired_cert(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)

    # Write a pre-expired cert/key pair directly, bypassing _generate's own
    # (always-future) validity window.
    key = ec.generate_private_key(ec.SECP256R1())
    now = datetime.datetime.now(datetime.UTC)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "GoogleFindMyTools")])
    expired_cert = (
        x509.CertificateBuilder()
        .subject_name(subject).issuer_name(issuer).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=10))
        .not_valid_after(now - datetime.timedelta(days=1))  # already expired
        .sign(key, hashes.SHA256())
    )
    config.TLS_CERT_PATH.write_bytes(expired_cert.public_bytes(serialization.Encoding.PEM))
    config.TLS_KEY_PATH.write_bytes(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ))
    old_cert_bytes = config.TLS_CERT_PATH.read_bytes()

    cert_path, key_path = tls.ensure_cert()

    assert config.TLS_CERT_PATH.read_bytes() != old_cert_bytes  # regenerated, not reused
    with open(cert_path, "rb") as f:
        cert = x509.load_pem_x509_certificate(f.read())
    assert cert.not_valid_after_utc > now


def test_ensure_cert_honors_bring_your_own_override(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)

    own_cert = tmp_path / "own_cert.pem"
    own_key = tmp_path / "own_key.pem"
    own_cert.write_text("not a real cert, just needs to exist")
    own_key.write_text("not a real key, just needs to exist")
    monkeypatch.setattr(config, "GFMT_TLS_CERT_PATH", str(own_cert))
    monkeypatch.setattr(config, "GFMT_TLS_KEY_PATH", str(own_key))

    cert_path, key_path = tls.ensure_cert()
    assert (cert_path, key_path) == (str(own_cert), str(own_key))
    assert not config.TLS_CERT_PATH.exists()  # no self-signed cert generated


def test_ensure_cert_raises_if_only_one_override_is_set(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)

    own_cert = tmp_path / "own_cert.pem"
    own_cert.write_text("not a real cert, just needs to exist")
    monkeypatch.setattr(config, "GFMT_TLS_CERT_PATH", str(own_cert))
    # GFMT_TLS_KEY_PATH left unset

    with pytest.raises(FileNotFoundError):
        tls.ensure_cert()


def test_ensure_cert_raises_if_an_override_path_does_not_exist(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)

    monkeypatch.setattr(config, "GFMT_TLS_CERT_PATH", str(tmp_path / "missing_cert.pem"))
    monkeypatch.setattr(config, "GFMT_TLS_KEY_PATH", str(tmp_path / "missing_key.pem"))

    with pytest.raises(FileNotFoundError):
        tls.ensure_cert()


def test_ensure_cert_includes_extra_sans_from_config(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(config, "GFMT_TLS_SAN", "my-nas.local, 192.168.1.50")

    cert_path, _ = tls.ensure_cert()
    with open(cert_path, "rb") as f:
        cert = x509.load_pem_x509_certificate(f.read())
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value

    assert "my-nas.local" in san.get_values_for_type(x509.DNSName)
    assert ipaddress.ip_address("192.168.1.50") in san.get_values_for_type(x509.IPAddress)
