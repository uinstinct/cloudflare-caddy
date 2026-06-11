"""Private key, CSR and certificate handling.

The private key is always generated locally and never leaves the host: we send
Cloudflare a CSR and it returns only the signed certificate. The same key is
reused to mint a self-signed cert in offline mode so Caddy can start without a
Cloudflare account (used by CI and local development).
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

CERT_FILENAME = "origin.pem"
KEY_FILENAME = "origin.key"

_KEY_SIZE = 2048


def generate_private_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=_KEY_SIZE)


def private_key_pem(key: rsa.RSAPrivateKey) -> bytes:
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def build_csr(key: rsa.RSAPrivateKey, hostnames: list[str]) -> bytes:
    """Build a PEM CSR with every hostname as a SAN (Cloudflare ignores the CN)."""
    builder = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostnames[0])]))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(h) for h in hostnames]),
            critical=False,
        )
    )
    return builder.sign(key, hashes.SHA256()).public_bytes(serialization.Encoding.PEM)


def self_signed_cert(key: rsa.RSAPrivateKey, hostnames: list[str], days: int) -> bytes:
    """Mint a self-signed certificate covering ``hostnames`` (offline mode only)."""
    now = dt.datetime.now(dt.UTC)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostnames[0])])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=1))
        .not_valid_after(now + dt.timedelta(days=days))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(h) for h in hostnames]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM)


def _san_dns_names(cert: x509.Certificate) -> list[str]:
    try:
        ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
    except x509.ExtensionNotFound:
        return []
    return ext.value.get_values_for_type(x509.DNSName)


def _public_der(public_key) -> bytes:
    return public_key.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def evaluate_local_cert(
    certs_dir: Path,
    required_hostnames: list[str],
    renew_before_days: int,
) -> tuple[bool, str]:
    """Return ``(is_usable, reason)`` for the certificate already on disk.

    A cert is usable only if it parses, its key matches, it is not expiring
    within ``renew_before_days`` and it covers every required hostname. Any
    other state returns ``False`` so the caller regenerates it.
    """
    cert_path = certs_dir / CERT_FILENAME
    key_path = certs_dir / KEY_FILENAME
    if not cert_path.exists() or not key_path.exists():
        return False, "no certificate on disk yet"

    try:
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    except ValueError as exc:
        return False, f"certificate is unreadable ({exc})"
    try:
        key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    except (ValueError, TypeError) as exc:
        return False, f"private key is unreadable ({exc})"

    if _public_der(key.public_key()) != _public_der(cert.public_key()):
        return False, "private key does not match the certificate"

    now = dt.datetime.now(dt.UTC)
    not_after = cert.not_valid_after_utc
    if not_after <= now:
        return False, f"certificate expired on {not_after.date()}"
    if not_after - now < dt.timedelta(days=renew_before_days):
        return False, f"certificate expires within {renew_before_days} days (on {not_after.date()})"

    san = set(_san_dns_names(cert))
    missing = [h for h in required_hostnames if h not in san]
    if missing:
        return False, f"certificate is missing hostnames: {', '.join(missing)}"

    return True, f"valid until {not_after.date()}, covers {', '.join(sorted(san))}"


def write_cert_files(certs_dir: Path, cert_pem: bytes, key_pem: bytes) -> None:
    certs_dir.mkdir(parents=True, exist_ok=True)
    cert_path = certs_dir / CERT_FILENAME
    key_path = certs_dir / KEY_FILENAME
    cert_path.write_bytes(cert_pem)
    cert_path.chmod(0o644)
    key_path.write_bytes(key_pem)
    key_path.chmod(0o600)
