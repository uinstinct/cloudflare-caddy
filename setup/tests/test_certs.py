from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.x509.oid import NameOID

from cf_setup import certs

HOSTNAMES = ["example.com", "*.example.com"]


def test_build_csr_has_san_and_cn():
    key = certs.generate_private_key()
    csr = x509.load_pem_x509_csr(certs.build_csr(key, HOSTNAMES))
    san = csr.extensions.get_extension_for_class(x509.SubjectAlternativeName)
    assert san.value.get_values_for_type(x509.DNSName) == HOSTNAMES
    cn = csr.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
    assert cn == "example.com"
    assert csr.is_signature_valid


def test_self_signed_cert_covers_hostnames():
    key = certs.generate_private_key()
    cert = x509.load_pem_x509_certificate(certs.self_signed_cert(key, HOSTNAMES, 90))
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
    assert san.value.get_values_for_type(x509.DNSName) == HOSTNAMES
    bc = cert.extensions.get_extension_for_class(x509.BasicConstraints)
    assert bc.value.ca is False


def test_private_key_pem_roundtrips():
    key = certs.generate_private_key()
    loaded = serialization.load_pem_private_key(certs.private_key_pem(key), password=None)
    assert loaded.public_key().public_numbers() == key.public_key().public_numbers()


def _write(tmp_path, hostnames, days):
    key = certs.generate_private_key()
    cert_pem = certs.self_signed_cert(key, hostnames, days)
    certs.write_cert_files(tmp_path, cert_pem, certs.private_key_pem(key))
    return key


def test_evaluate_missing_files(tmp_path):
    usable, reason = certs.evaluate_local_cert(tmp_path, HOSTNAMES, 30)
    assert usable is False
    assert "no certificate" in reason


def test_evaluate_valid_cert(tmp_path):
    _write(tmp_path, HOSTNAMES, 365)
    usable, reason = certs.evaluate_local_cert(tmp_path, HOSTNAMES, 30)
    assert usable is True
    assert "valid until" in reason


def test_evaluate_expiring_soon(tmp_path):
    _write(tmp_path, HOSTNAMES, 10)
    usable, reason = certs.evaluate_local_cert(tmp_path, HOSTNAMES, 30)
    assert usable is False
    assert "expires within" in reason


def test_evaluate_missing_hostname(tmp_path):
    _write(tmp_path, ["example.com"], 365)
    usable, reason = certs.evaluate_local_cert(tmp_path, HOSTNAMES, 30)
    assert usable is False
    assert "missing hostnames" in reason
    assert "*.example.com" in reason


def test_evaluate_key_mismatch(tmp_path):
    # Cert from one key, key file from a different key.
    _write(tmp_path, HOSTNAMES, 365)
    other = certs.generate_private_key()
    (tmp_path / certs.KEY_FILENAME).write_bytes(certs.private_key_pem(other))
    usable, reason = certs.evaluate_local_cert(tmp_path, HOSTNAMES, 30)
    assert usable is False
    assert "does not match" in reason


def test_key_file_permissions(tmp_path):
    _write(tmp_path, HOSTNAMES, 365)
    mode = (tmp_path / certs.KEY_FILENAME).stat().st_mode & 0o777
    assert mode == 0o600
