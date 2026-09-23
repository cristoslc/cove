"""TLS certificate management — replaces mkcert.

Generates a self-signed root CA, installs it into the system trust store,
and signs leaf certificates for Cove's wildcard domains.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID


# ── Paths ─────────────────────────────────────────────────────────────────────

def _ca_dir() -> Path:
    env = os.environ.get("COVE_PKI_DIR")
    if env:
        return Path(env)
    return Path.home() / ".config" / "cove" / "pki"


def _root_ca_cert_path() -> Path:
    return _ca_dir() / "rootCA.pem"


def _root_ca_key_path() -> Path:
    return _ca_dir() / "rootCA-key.pem"


def ca_path() -> Path:
    """Return the CA directory path (analogous to ``mkcert -CAROOT``)."""
    return _ca_dir()


def root_ca_pem() -> str:
    """Return the root CA certificate in PEM format."""
    return _root_ca_cert_path().read_text()


# ── CA generation ──────────────────────────────────────────────────────────────

def _generate_ca(key_path: Path, cert_path: Path) -> None:
    """Generate a self-signed root CA key and certificate."""
    key = ec.generate_private_key(ec.SECP256R1())
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "Cove Root CA"),
    ])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                key_cert_sign=True,
                crl_sign=True,
                digital_signature=False,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ))
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def _load_ca():
    """Load the root CA private key and certificate.

    Returns ``(private_key, certificate)`` or ``(None, None)`` if missing.
    """
    key_path = _root_ca_key_path()
    cert_path = _root_ca_cert_path()
    if not key_path.exists() or not cert_path.exists():
        return None, None
    key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    return key, cert


# ── Leaf cert signing ────────────────────────────────────────────────────────

def _generate_leaf(
    ca_key_path: Path,
    ca_cert_path: Path,
    sans: list[str],
    key_out: Path,
    cert_out: Path,
) -> None:
    """Generate a leaf certificate signed by the CA."""
    ca_key = serialization.load_pem_private_key(ca_key_path.read_bytes(), password=None)
    ca_cert = x509.load_pem_x509_certificate(ca_cert_path.read_bytes())

    key = ec.generate_private_key(ec.SECP256R1())
    now = datetime.now(timezone.utc)

    san_entries: list[x509.GeneralName] = []
    for name in sans:
        try:
            san_entries.append(x509.IPAddress(_parse_ip(name)))
        except ValueError:
            san_entries.append(x509.DNSName(name))

    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "Cove"),
        ]))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=True,
                key_cert_sign=False,
                crl_sign=False,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .add_extension(
            x509.SubjectAlternativeName(san_entries),
            critical=False,
        )
        # RFC 5280: the AKI on CA-issued certs is REQUIRED by macOS
        # Security.framework / python-ssl; its absence makes verification
        # fail with "Missing Authority Key Identifier" even though
        # openssl CLI verifies fine.
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_cert.public_key()),
            critical=False,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    key_out.parent.mkdir(parents=True, exist_ok=True)
    key_out.write_bytes(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ))
    cert_out.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def _parse_ip(value: str):
    """Parse an IP address string, supporting both IPv4 and IPv6."""
    import ipaddress
    return ipaddress.ip_address(value)


# ── Trust store install ──────────────────────────────────────────────────────

def _is_ca_installed() -> bool:
    """Check whether the root CA is already in the system trust store."""
    cert_path = _root_ca_cert_path()
    if not cert_path.exists():
        return False
    if sys.platform == "darwin":
        result = subprocess.run(
            ["security", "find-certificate", "-c", "Cove Root CA", "-a"],
            capture_output=True, text=True,
        )
        return "1 identity" in result.stdout
    if sys.platform == "linux":
        result = subprocess.run(
            ["update-ca-certificates", "--check"],
            capture_output=True, text=True,
        )
        return result.returncode == 0
    return False


def _install_ca_macos(cert_path: Path) -> None:
    """Install the root CA into the macOS system Keychain."""
    subprocess.run(
        [
            "security", "add-trusted-cert", "-d", "-r", "trustRoot",
            "-k", "/Library/Keychains/System.keychain",
            str(cert_path),
        ],
        check=True,
    )


def _install_ca_linux(cert_path: Path) -> None:
    """Install the root CA into the Linux system trust store."""
    if sys.platform != "linux":
        raise NotImplementedError(f"unsupported platform: {sys.platform}")
    dest = Path("/usr/local/share/ca-certificates/cove-root-ca.crt")
    dest.write_bytes(cert_path.read_bytes())
    subprocess.run(["update-ca-certificates"], check=True)


# ── Public API ────────────────────────────────────────────────────────────────

def _ensure_ca() -> None:
    """Generate the root CA if it doesn't already exist (idempotent)."""
    cert_path = _root_ca_cert_path()
    key_path = _root_ca_key_path()
    if cert_path.exists() and key_path.exists():
        return
    _generate_ca(key_path, cert_path)


def ensure_ca() -> None:
    """Generate the root CA and install it into the system trust store.

    Idempotent — skips generation if CA exists, skips install if already trusted.
    """
    _ensure_ca()
    if _is_ca_installed():
        return
    cert_path = _root_ca_cert_path()
    if sys.platform == "darwin":
        _install_ca_macos(cert_path)
    elif sys.platform == "linux":
        _install_ca_linux(cert_path)


def sign_cert(sans: list[str], key_file: Path, cert_file: Path) -> None:
    """Generate a TLS certificate signed by the root CA.

    Idempotent — skips if the cert already exists with the same SANs.
    To force regeneration, delete the output files first.

    Args:
        sans: Subject Alternative Names (DNS names and IP addresses).
        key_file: Path to write the private key.
        cert_file: Path to write the certificate.
    """
    if cert_file.exists() and key_file.exists():
        existing = x509.load_pem_x509_certificate(cert_file.read_bytes())
        try:
            ext = existing.extensions.get_extension_for_class(x509.SubjectAlternativeName)
            existing_sans = {e.value for e in ext.value}
            if set(sans) == existing_sans:
                return
        except x509.ExtensionNotFound:
            pass

    _ensure_ca()
    _generate_leaf(
        _root_ca_key_path(),
        _root_ca_cert_path(),
        sans,
        key_file,
        cert_file,
    )
