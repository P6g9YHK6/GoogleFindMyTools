"""Self-signed TLS cert/key for the opt-in HTTPS_ENABLED toggle (see
webui/config.py and webui/serve.py, the Docker image's actual entrypoint).

ensure_cert() is the only thing callers need: it generates a cert on first
use, persists it in DATA_DIR so it survives a restart (regenerating it every
boot would invalidate any browser trust exception the user manually added
for it), and transparently regenerates it once it's expired. A
GFMT_TLS_CERT_PATH/GFMT_TLS_KEY_PATH override lets an operator bring their
own cert instead - see its docstring for exactly how that's handled.
"""

import datetime
import ipaddress
import logging
import os

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from webui import config

logger = logging.getLogger("webui.tls")

# Regenerate this far before actual expiry, not just once already-expired -
# a cert that dies mid-restart-window is worse than one regenerated a bit
# early.
_RENEWAL_GRACE = datetime.timedelta(days=30)

_DEFAULT_SAN = ["localhost", "127.0.0.1", "::1"]


def _parse_san(raw: str | None) -> list[str]:
    extra = [entry.strip() for entry in (raw or "").split(",") if entry.strip()]
    return _DEFAULT_SAN + extra


def _san_entries(hostnames_and_ips: list[str]) -> list[x509.GeneralName]:
    entries: list[x509.GeneralName] = []
    for value in hostnames_and_ips:
        try:
            entries.append(x509.IPAddress(ipaddress.ip_address(value)))
        except ValueError:
            entries.append(x509.DNSName(value))
    return entries


def _generate(cert_path: str, key_path: str) -> None:
    key = ec.generate_private_key(ec.SECP256R1())

    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "GoogleFindMyTools")])
    now = datetime.datetime.now(datetime.UTC)
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))  # small clock-skew cushion
        .not_valid_after(now + datetime.timedelta(days=config.GFMT_TLS_VALIDITY_DAYS))
        .add_extension(x509.SubjectAlternativeName(_san_entries(_parse_san(config.GFMT_TLS_SAN))), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, key_encipherment=True, content_commitment=False, data_encipherment=False,
                key_agreement=False, key_cert_sign=False, crl_sign=False, encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
    )
    cert = builder.sign(key, hashes.SHA256())

    config.DATA_DIR.mkdir(parents=True, exist_ok=True)

    key_bytes = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    # Sensitive material sitting in a shared volume - write it private from
    # the moment it exists rather than chmod-ing after the fact.
    fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(key_bytes)

    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    fingerprint = cert.fingerprint(hashes.SHA256()).hex(":").upper()
    logger.info(
        "Generated a self-signed TLS certificate (valid %d days, SHA-256 fingerprint %s) at %s / %s - "
        "your browser will warn about it being untrusted the first time; that's expected for a "
        "self-signed cert, not an error.",
        config.GFMT_TLS_VALIDITY_DAYS, fingerprint, cert_path, key_path,
    )


def _is_still_valid(cert_path: str) -> bool:
    with open(cert_path, "rb") as f:
        cert = x509.load_pem_x509_certificate(f.read())
    return datetime.datetime.now(datetime.UTC) < (cert.not_valid_after_utc - _RENEWAL_GRACE)


def ensure_cert() -> tuple[str, str]:
    """Returns (cert_path, key_path) as strings, ready to hand straight to
    uvicorn's ssl_certfile/ssl_keyfile. Generates and persists a self-signed
    cert on first call; later calls reuse it until it's within
    _RENEWAL_GRACE of expiring, then transparently regenerate it (logging a
    warning, since that invalidates any trust exception a browser already
    has for the old one)."""
    override_cert, override_key = config.GFMT_TLS_CERT_PATH, config.GFMT_TLS_KEY_PATH
    if override_cert or override_key:
        # Only honored if BOTH point at real files - an operator who set
        # one of these believes they've configured a real cert, and
        # silently falling back to self-signed instead would leave that
        # discovered only once some client hard-fails on it.
        if not (override_cert and override_key and os.path.exists(override_cert) and os.path.exists(override_key)):
            raise FileNotFoundError(
                f"GFMT_TLS_CERT_PATH/GFMT_TLS_KEY_PATH are set but don't both point at existing files "
                f"(cert={override_cert!r}, key={override_key!r}) - set both to real files, or unset both "
                f"to generate a self-signed cert instead."
            )
        return override_cert, override_key

    cert_path, key_path = str(config.TLS_CERT_PATH), str(config.TLS_KEY_PATH)
    if os.path.exists(cert_path) and os.path.exists(key_path):
        if _is_still_valid(cert_path):
            return cert_path, key_path
        logger.warning(
            "Existing self-signed TLS certificate at %s is expired (or expiring soon) - regenerating it. "
            "Any browser trust exception for the old one will need to be re-added.",
            cert_path,
        )

    _generate(cert_path, key_path)
    return cert_path, key_path
