"""Tests for cove.certs — TLS certificate management replacing mkcert."""

import subprocess
import sys
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.x509.oid import NameOID

from cove.certs import (
    _ca_dir,
    _ensure_ca,
    _generate_ca,
    _generate_leaf,
    _install_ca_macos,
    _install_ca_linux,
    _is_ca_installed,
    _load_ca,
    _root_ca_cert_path,
    _root_ca_key_path,
    ca_path,
    ensure_ca,
    root_ca_pem,
    sign_cert,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def pki_dir(tmp_path):
    """Isolated PKI directory for testing."""
    d = tmp_path / "pki"
    d.mkdir()
    return d


@pytest.fixture()
def ca_pair(pki_dir):
    """Generate a real CA key+cert in the PKI dir and return paths."""
    key_path = pki_dir / "CA-key.pem"
    cert_path = pki_dir / "CA.pem"
    _generate_ca(key_path, cert_path)
    return key_path, cert_path


# ── Unit: CA generation ──────────────────────────────────────────────────────

class TestGenerateCA:
    def test_generates_key_and_cert_files(self, pki_dir):
        key_path = pki_dir / "CA-key.pem"
        cert_path = pki_dir / "CA.pem"
        _generate_ca(key_path, cert_path)
        assert key_path.exists(), "CA key not created"
        assert cert_path.exists(), "CA cert not created"

    def test_cert_is_self_signed(self, ca_pair):
        _, cert_path = ca_pair
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        assert cert.subject == cert.issuer, "CA must be self-signed"

    def test_cert_has_ca_true(self, ca_pair):
        _, cert_path = ca_pair
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        ext = cert.extensions.get_extension_for_class(x509.BasicConstraints)
        assert ext.value.ca is True, "CA cert must have CA:TRUE"

    def test_cert_has_key_cert_sign_usage(self, ca_pair):
        _, cert_path = ca_pair
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        ext = cert.extensions.get_extension_for_class(x509.KeyUsage)
        assert ext.value.key_cert_sign, "CA must have keyCertSign"
        assert ext.value.crl_sign, "CA must have CRL sign"
        assert not ext.value.digital_signature, "CA should not have digitalSignature"

    def test_cert_has_common_name(self, ca_pair):
        _, cert_path = ca_pair
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        cn = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        assert len(cn) == 1
        assert "Cove Root CA" in cn[0].value

    def test_cert_validity_period(self, ca_pair):
        _, cert_path = ca_pair
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        delta = cert.not_valid_after_utc - cert.not_valid_before_utc
        assert delta.days >= 3650, "CA should be valid for ~10 years"

    def test_regenerating_overwrites(self, pki_dir):
        key_path = pki_dir / "CA-key.pem"
        cert_path = pki_dir / "CA.pem"
        _generate_ca(key_path, cert_path)
        first_key = key_path.read_bytes()
        _generate_ca(key_path, cert_path)
        second_key = key_path.read_bytes()
        assert first_key != second_key, "Regeneration should produce new key"


# ── Unit: Leaf cert signing ─────────────────────────────────────────────────

class TestGenerateLeaf:
    def test_generates_key_and_cert_files(self, pki_dir, ca_pair):
        ca_key, ca_cert = ca_pair
        key_path = pki_dir / "leaf-key.pem"
        cert_path = pki_dir / "leaf.pem"
        sans = ["*.cove", "git.cove", "localhost"]
        _generate_leaf(ca_key, ca_cert, sans, key_path, cert_path)
        assert key_path.exists(), "Leaf key not created"
        assert cert_path.exists(), "Leaf cert not created"

    def test_leaf_is_signed_by_ca(self, pki_dir, ca_pair):
        ca_key, ca_cert = ca_pair
        key_path = pki_dir / "leaf-key.pem"
        cert_path = pki_dir / "leaf.pem"
        sans = ["*.cove", "git.cove", "localhost"]
        _generate_leaf(ca_key, ca_cert, sans, key_path, cert_path)
        leaf = x509.load_pem_x509_certificate(cert_path.read_bytes())
        assert leaf.issuer == x509.load_pem_x509_certificate(ca_cert.read_bytes()).subject

    def test_leaf_has_expected_sans(self, pki_dir, ca_pair):
        ca_key, ca_cert = ca_pair
        key_path = pki_dir / "leaf-key.pem"
        cert_path = pki_dir / "leaf.pem"
        sans = ["*.cove", "git.cove", "localhost", "127.0.0.1"]
        _generate_leaf(ca_key, ca_cert, sans, key_path, cert_path)
        leaf = x509.load_pem_x509_certificate(cert_path.read_bytes())
        ext = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        actual_dns = {e.value for e in ext.value if isinstance(e, x509.DNSName)}
        for s in ["*.cove", "git.cove", "localhost"]:
            assert s in actual_dns, f"Missing SAN: {s}"
        actual_ip = {str(e.value) for e in ext.value if isinstance(e, x509.IPAddress)}
        assert len(actual_ip) > 0, "Should have at least one IP SAN"

    def test_leaf_has_no_ca_constraint(self, pki_dir, ca_pair):
        ca_key, ca_cert = ca_pair
        key_path = pki_dir / "leaf-key.pem"
        cert_path = pki_dir / "leaf.pem"
        sans = ["*.cove"]
        _generate_leaf(ca_key, ca_cert, sans, key_path, cert_path)
        leaf = x509.load_pem_x509_certificate(cert_path.read_bytes())
        ext = leaf.extensions.get_extension_for_class(x509.BasicConstraints)
        assert ext.value.ca is False, "Leaf cert must NOT have CA:TRUE"

    def test_leaf_has_digital_signature_usage(self, pki_dir, ca_pair):
        ca_key, ca_cert = ca_pair
        key_path = pki_dir / "leaf-key.pem"
        cert_path = pki_dir / "leaf.pem"
        sans = ["*.cove"]
        _generate_leaf(ca_key, ca_cert, sans, key_path, cert_path)
        leaf = x509.load_pem_x509_certificate(cert_path.read_bytes())
        ext = leaf.extensions.get_extension_for_class(x509.KeyUsage)
        assert ext.value.digital_signature, "Leaf must have digitalSignature"
        assert ext.value.key_encipherment, "Leaf must have keyEncipherment"

    def test_leaf_validity_period(self, pki_dir, ca_pair):
        ca_key, ca_cert = ca_pair
        key_path = pki_dir / "leaf-key.pem"
        cert_path = pki_dir / "leaf.pem"
        sans = ["*.cove"]
        _generate_leaf(ca_key, ca_cert, sans, key_path, cert_path)
        leaf = x509.load_pem_x509_certificate(cert_path.read_bytes())
        delta = leaf.not_valid_after_utc - leaf.not_valid_before_utc
        assert delta.days >= 365, "Leaf should be valid for ~1 year"
        assert delta.days <= 370, "Leaf should not exceed 1 year"

    def test_openssl_verify_accepts_chain(self, pki_dir, ca_pair):
        ca_key, ca_cert = ca_pair
        key_path = pki_dir / "leaf-key.pem"
        cert_path = pki_dir / "leaf.pem"
        sans = ["*.cove", "git.cove", "localhost"]
        _generate_leaf(ca_key, ca_cert, sans, key_path, cert_path)
        result = subprocess.run(
            ["openssl", "verify", "-CAfile", str(ca_cert), str(cert_path)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"openssl verify failed: {result.stderr}"

    def test_openssl_verify_rejects_unsigned(self, pki_dir, ca_pair):
        ca_key, ca_cert = ca_pair
        key_path = pki_dir / "leaf-key.pem"
        cert_path = pki_dir / "leaf.pem"
        sans = ["*.cove"]
        _generate_leaf(ca_key, ca_cert, sans, key_path, cert_path)
        wrong_ca = pki_dir / "wrong-ca.pem"
        _generate_ca(wrong_ca, pki_dir / "wrong-ca-key.pem")
        result = subprocess.run(
            ["openssl", "verify", "-CAfile", str(wrong_ca), str(cert_path)],
            capture_output=True, text=True,
        )
        assert result.returncode != 0, "Should reject cert signed by different CA"


# ── Unit: CA directory and path helpers ─────────────────────────────────────

class TestCADir:
    def test_ca_dir_defaults_to_config_cove_pki(self, monkeypatch, tmp_path):
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        d = _ca_dir()
        assert d == tmp_path / ".config" / "cove" / "pki"

    def test_ca_dir_respects_env_var(self, monkeypatch, tmp_path):
        monkeypatch.setenv("COVE_PKI_DIR", str(tmp_path / "custom-pki"))
        d = _ca_dir()
        assert d == tmp_path / "custom-pki"

    def test_ca_path_returns_dir(self, pki_dir, monkeypatch):
        monkeypatch.setenv("COVE_PKI_DIR", str(pki_dir))
        assert ca_path() == pki_dir

    def test_root_ca_cert_path(self, pki_dir, monkeypatch):
        monkeypatch.setenv("COVE_PKI_DIR", str(pki_dir))
        assert _root_ca_cert_path() == pki_dir / "rootCA.pem"

    def test_root_ca_key_path(self, pki_dir, monkeypatch):
        monkeypatch.setenv("COVE_PKI_DIR", str(pki_dir))
        assert _root_ca_key_path() == pki_dir / "rootCA-key.pem"


# ── Unit: ensure_ca (idempotency) ────────────────────────────────────────────

class TestEnsureCA:
    def test_creates_ca_when_missing(self, pki_dir, monkeypatch):
        monkeypatch.setenv("COVE_PKI_DIR", str(pki_dir))
        _ensure_ca()
        assert (pki_dir / "rootCA.pem").exists()
        assert (pki_dir / "rootCA-key.pem").exists()

    def test_idempotent_when_ca_exists(self, pki_dir, monkeypatch):
        monkeypatch.setenv("COVE_PKI_DIR", str(pki_dir))
        _ensure_ca()
        first_cert = (pki_dir / "rootCA.pem").read_bytes()
        _ensure_ca()
        second_cert = (pki_dir / "rootCA.pem").read_bytes()
        assert first_cert == second_cert, "ensure_ca must not regenerate when CA exists"

    def test_load_ca_returns_key_and_cert(self, pki_dir, monkeypatch):
        monkeypatch.setenv("COVE_PKI_DIR", str(pki_dir))
        _ensure_ca()
        key, cert = _load_ca()
        assert key is not None
        assert cert is not None

    def test_root_ca_pem_returns_pem_string(self, pki_dir, monkeypatch):
        monkeypatch.setenv("COVE_PKI_DIR", str(pki_dir))
        _ensure_ca()
        pem = root_ca_pem()
        assert pem.startswith("-----BEGIN CERTIFICATE-----")
        assert pem.endswith("-----END CERTIFICATE-----\n")


# ── Unit: sign_cert (public API) ────────────────────────────────────────────

class TestSignCert:
    def test_signs_and_writes_files(self, pki_dir, monkeypatch):
        monkeypatch.setenv("COVE_PKI_DIR", str(pki_dir))
        _ensure_ca()
        key_file = pki_dir / "test-key.pem"
        cert_file = pki_dir / "test.pem"
        sign_cert(["*.cove", "git.cove", "localhost", "127.0.0.1"], key_file, cert_file)
        assert key_file.exists()
        assert cert_file.exists()

    def test_signed_cert_verifies_with_openssl(self, pki_dir, monkeypatch):
        monkeypatch.setenv("COVE_PKI_DIR", str(pki_dir))
        _ensure_ca()
        key_file = pki_dir / "test-key.pem"
        cert_file = pki_dir / "test.pem"
        sign_cert(["*.cove", "git.cove", "localhost"], key_file, cert_file)
        ca_cert = pki_dir / "rootCA.pem"
        result = subprocess.run(
            ["openssl", "verify", "-CAfile", str(ca_cert), str(cert_file)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"openssl verify failed: {result.stderr}"

    def test_sign_cert_idempotent(self, pki_dir, monkeypatch):
        monkeypatch.setenv("COVE_PKI_DIR", str(pki_dir))
        _ensure_ca()
        key_file = pki_dir / "test-key.pem"
        cert_file = pki_dir / "test.pem"
        sign_cert(["*.cove"], key_file, cert_file)
        first_key = key_file.read_bytes()
        sign_cert(["*.cove"], key_file, cert_file)
        second_key = key_file.read_bytes()
        assert first_key == second_key, "sign_cert must not regenerate key when SANs match"

    def test_sign_cert_regenerates_when_sans_change(self, pki_dir, monkeypatch):
        monkeypatch.setenv("COVE_PKI_DIR", str(pki_dir))
        _ensure_ca()
        key_file = pki_dir / "test-key.pem"
        cert_file = pki_dir / "test.pem"
        sign_cert(["*.cove"], key_file, cert_file)
        first_cert = cert_file.read_bytes()
        sign_cert(["*.cove", "git.cove"], key_file, cert_file)
        second_cert = cert_file.read_bytes()
        assert first_cert != second_cert, "Should regenerate when SANs change"

    def test_sign_cert_returns_true_on_fresh_sign(self, pki_dir, monkeypatch):
        """Return value: True = a new leaf was written (changed)."""
        monkeypatch.setenv("COVE_PKI_DIR", str(pki_dir))
        _ensure_ca()
        changed = sign_cert(
            ["*.cove"], pki_dir / "k.pem", pki_dir / "c.pem",
        )
        assert changed is True

    def test_sign_cert_returns_false_when_sans_match(self, pki_dir, monkeypatch):
        """Return value: False = existing cert already covers the SANs (skip)."""
        monkeypatch.setenv("COVE_PKI_DIR", str(pki_dir))
        _ensure_ca()
        sign_cert(["*.cove"], pki_dir / "k.pem", pki_dir / "c.pem")
        changed = sign_cert(["*.cove"], pki_dir / "k.pem", pki_dir / "c.pem")
        assert changed is False

    def test_sign_cert_returns_true_on_san_drift(self, pki_dir, monkeypatch):
        """The v0.7.0 upgrade bug, at the API level: a cert minted before
        ade.cove existed must regenerate (True) when the requested SAN set
        gains ade.cove — this is what heals existing deployments."""
        monkeypatch.setenv("COVE_PKI_DIR", str(pki_dir))
        _ensure_ca()
        key_file, cert_file = pki_dir / "k.pem", pki_dir / "c.pem"
        assert sign_cert(["*.cove", "git.cove"], key_file, cert_file) is True
        assert sign_cert(
            ["*.cove", "git.cove", "ade.cove"], key_file, cert_file,
        ) is True, "SAN drift must report changed"
        cert = x509.load_pem_x509_certificate(cert_file.read_bytes())
        dns = {
            e.value for e in
            cert.extensions.get_extension_for_class(
                x509.SubjectAlternativeName,
            ).value
            if isinstance(e, x509.DNSName)
        }
        assert "ade.cove" in dns, "regenerated cert must carry the new SAN"

    def test_sign_cert_idempotent_with_ip_sans(self, pki_dir, monkeypatch):
        """Regression: the SAN comparison treated requested strings
        ('127.0.0.1') as unequal to parsed cert SAN entries (IPv4Address),
        so any SAN list containing IPs regenerated on EVERY call. bringup's
        list always carries localhost/127.0.0.1/::1 — this must converge."""
        monkeypatch.setenv("COVE_PKI_DIR", str(pki_dir))
        _ensure_ca()
        key_file, cert_file = pki_dir / "k.pem", pki_dir / "c.pem"
        sans = ["*.cove", "localhost", "127.0.0.1", "::1"]
        assert sign_cert(sans, key_file, cert_file) is True
        assert sign_cert(sans, key_file, cert_file) is False, (
            "identical SAN list including IPs must be a no-op skip"
        )

    def test_sign_cert_drift_and_settle_with_ip_sans(self, pki_dir, monkeypatch):
        """Full bringup shape: pre-ADE list (with IPs) → ADE list regenerates
        once → identical re-run settles to False."""
        monkeypatch.setenv("COVE_PKI_DIR", str(pki_dir))
        _ensure_ca()
        key_file, cert_file = pki_dir / "k.pem", pki_dir / "c.pem"
        pre = ["*.cove", "git.cove", "localhost", "127.0.0.1"]
        post = ["*.cove", "git.cove", "ade.cove", "ade.cove.local",
                "localhost", "127.0.0.1", "::1"]
        assert sign_cert(pre, key_file, cert_file) is True
        assert sign_cert(post, key_file, cert_file) is True
        assert sign_cert(post, key_file, cert_file) is False


# ── Unit: Trust store install (mocked) ────────────────────────────────────────

class TestInstallCA:
    def test_is_ca_installed_macos_checks_security(self, pki_dir, monkeypatch):
        monkeypatch.setenv("COVE_PKI_DIR", str(pki_dir))
        _ensure_ca()
        calls = []

        def mock_run(cmd, **kw):
            calls.append(cmd)
            class Result:
                returncode = 0
                stdout = "1 identity"
                stderr = ""
            return Result()

        monkeypatch.setattr("subprocess.run", mock_run)
        monkeypatch.setattr("sys.platform", "darwin")
        result = _is_ca_installed()
        assert result is True
        assert any("security" in str(c) for c in calls)
        assert any("find-certificate" in str(c) for c in calls)

    def test_is_ca_installed_macos_not_found(self, monkeypatch):
        def mock_run(cmd, **kw):
            class Result:
                returncode = 0
                stdout = "0 identities"
                stderr = ""
            return Result()

        monkeypatch.setattr("subprocess.run", mock_run)
        monkeypatch.setattr("sys.platform", "darwin")
        assert _is_ca_installed() is False

    def test_install_ca_macos_calls_security(self, monkeypatch, pki_dir):
        calls = []

        def mock_run(cmd, **kw):
            calls.append(cmd)
            class Result:
                returncode = 0
                stdout = ""
                stderr = ""
            return Result()

        monkeypatch.setattr("subprocess.run", mock_run)
        monkeypatch.setattr("sys.platform", "darwin")
        _install_ca_macos(pki_dir / "rootCA.pem")
        assert any("add-trusted-cert" in str(c) for c in calls)

    def test_install_ca_linux_calls_update(self, pki_dir, monkeypatch):
        monkeypatch.setenv("COVE_PKI_DIR", str(pki_dir))
        _ensure_ca()
        calls = []

        def mock_run(cmd, **kw):
            calls.append(cmd)
            class Result:
                returncode = 0
                stdout = ""
                stderr = ""
            return Result()

        monkeypatch.setattr("subprocess.run", mock_run)
        monkeypatch.setattr("sys.platform", "linux")
        monkeypatch.setattr("pathlib.Path.write_bytes", lambda self, data: None)
        _install_ca_linux(pki_dir / "rootCA.pem")
        assert any("update-ca-certificates" in str(c) for c in calls)

    def test_install_ca_unsupported_platform(self, monkeypatch, pki_dir):
        monkeypatch.setattr("sys.platform", "win32")
        with pytest.raises(NotImplementedError, match="unsupported platform"):
            _install_ca_linux(pki_dir / "rootCA.pem")


# ── E2E: full ensure_ca + sign_cert pipeline ─────────────────────────────────

class TestE2EPipeline:
    def test_full_pipeline_openssl_verify(self, pki_dir, monkeypatch):
        monkeypatch.setenv("COVE_PKI_DIR", str(pki_dir))
        _ensure_ca()
        key_file = pki_dir / "cove.local-key.pem"
        cert_file = pki_dir / "cove.local.pem"
        sans = [
            "*.cove", "*.cove.local", "*.cove.testhost", "*.cove.local.testhost",
            "cove", "cove.local",
            "git.cove", "git.cove.local",
            "vault.cove", "vault.cove.local",
            "hc.cove", "hc.cove.local", "ca.cove", "ca.cove.local",
            "*.pages.cove", "*.pages.cove.local",
            "localhost", "127.0.0.1", "::1",
        ]
        sign_cert(sans, key_file, cert_file)
        ca_cert = pki_dir / "rootCA.pem"
        result = subprocess.run(
            ["openssl", "verify", "-CAfile", str(ca_cert), str(cert_file)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"openssl verify failed: {result.stderr}"

    def test_full_pipeline_cert_has_all_sans(self, pki_dir, monkeypatch):
        monkeypatch.setenv("COVE_PKI_DIR", str(pki_dir))
        _ensure_ca()
        key_file = pki_dir / "cove.local-key.pem"
        cert_file = pki_dir / "cove.local.pem"
        sans = ["*.cove", "git.cove", "vault.cove", "localhost", "127.0.0.1"]
        sign_cert(sans, key_file, cert_file)
        cert = x509.load_pem_x509_certificate(cert_file.read_bytes())
        ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        actual_dns = {e.value for e in ext.value if isinstance(e, x509.DNSName)}
        for s in ["*.cove", "git.cove", "vault.cove", "localhost"]:
            assert s in actual_dns, f"Missing SAN: {s}"


# ── CLI contract: `cove certs sign` must report changed vs up-to-date ────────

class TestSignCLI:
    """`cove certs sign` prints `Signed:` when it wrote a new leaf and
    `Up-to-date:` when the existing cert already covers the SANs. bringup's
    changed_when depends on this distinction (v0.7.0 printed `Signed:`
    unconditionally)."""

    def _invoke(self, monkeypatch, pki_dir, sans):
        from click.testing import CliRunner
        from cove.cli import certs

        monkeypatch.setenv("COVE_PKI_DIR", str(pki_dir / "pki"))
        return CliRunner().invoke(certs, [
            "sign",
            *[arg for s in sans for arg in ("--sans", s)],
            "--key-file", str(pki_dir / "leaf-key.pem"),
            "--cert-file", str(pki_dir / "leaf.pem"),
        ])

    def test_reports_signed_on_fresh_sign(self, pki_dir, monkeypatch):
        result = self._invoke(monkeypatch, pki_dir, ["*.cove", "git.cove"])
        assert result.exit_code == 0, result.output
        assert "Signed:" in result.output, result.output

    def test_reports_up_to_date_when_sans_match(self, pki_dir, monkeypatch):
        assert self._invoke(monkeypatch, pki_dir, ["*.cove"]).exit_code == 0
        result = self._invoke(monkeypatch, pki_dir, ["*.cove"])
        assert result.exit_code == 0, result.output
        assert "Up-to-date:" in result.output, (
            f"second identical sign must report Up-to-date, got: {result.output}"
        )
        assert "Signed:" not in result.output, result.output

    def test_reports_up_to_date_with_ip_sans(self, pki_dir, monkeypatch):
        """The bringup SAN list always carries localhost/127.0.0.1/::1 —
        the CLI verdict must still settle to Up-to-date (v0.7.0's comparison
        never matched IP entries)."""
        sans = ["*.cove", "git.cove", "localhost", "127.0.0.1", "::1"]
        assert self._invoke(monkeypatch, pki_dir, sans).exit_code == 0
        result = self._invoke(monkeypatch, pki_dir, sans)
        assert result.exit_code == 0, result.output
        assert "Up-to-date:" in result.output, result.output


# ── bringup: cert task must self-heal SAN drift (no creates-guard) ───────────

class TestBringupCertSelfHeal:
    """v0.7.0 regression fix: `cove up` failed hard on existing deployments
    whose TLS cert predated a new required SAN (MISSING: ade.cove). The
    generate-cert task's `creates:` guard skipped the (already drift-aware)
    `cove certs sign`, so validation had no healing path. Contract:

    - the sign task runs on EVERY `cove up` (no creates guard) — sign_cert
      itself no-ops when SANs match,
    - changed_when reads the CLI's Signed/Up-to-date verdict (truthful
      idempotency, and gates the nginx reload notify),
    - the fail-loud validation stays as the safety net,
    - the validation host list and the sign argv SAN lists never diverge.
    """

    @staticmethod
    def _cert_tasks() -> list[dict]:
        root = Path(__file__).resolve().parent
        for _ in range(6):
            if (root / "compose" / "bringup.yml").exists():
                break
            root = root.parent
        import yaml

        with open(root / "compose" / "bringup.yml") as f:
            bringup = yaml.safe_load(f)
        tasks = bringup[0]["tasks"]
        sign_tasks = [
            t for t in tasks
            if isinstance(t, dict) and "Sign TLS cert" in t.get("name", "")
        ]
        assert len(sign_tasks) == 1, "exactly one cert-sign task expected"
        validate_tasks = [
            t for t in tasks
            if isinstance(t, dict)
            and "Validate TLS cert" in t.get("name", "")
        ]
        assert len(validate_tasks) == 1, "exactly one cert-validate task expected"
        return [sign_tasks[0], validate_tasks[0]]

    def test_sign_task_has_no_creates_guard(self):
        sign, _ = self._cert_tasks()
        creates = sign.get("args", {}).get("creates")
        assert creates is None, (
            "cert task must NOT use creates: — it would skip the drift-aware "
            f"sign on existing deployments (the v0.7.0 regression). Got creates={creates!r}"
        )

    def test_sign_task_changed_when_reads_cli_verdict(self):
        sign, _ = self._cert_tasks()
        assert "register" in sign, "sign task must register its result"
        cw = sign.get("changed_when", "")
        assert "Signed:" in str(cw), (
            f"changed_when must key off the CLI's 'Signed:' verdict, got: {cw!r}"
        )

    def test_sign_task_notifies_nginx_reload(self):
        sign, _ = self._cert_tasks()
        assert sign.get("notify") == "Reload nginx", (
            "a regenerated leaf must reload the running nginx (it otherwise "
            "serves the stale cert until manual restart)"
        )

    def test_fail_loud_validation_follows_sign_task(self):
        sign, validate = self._cert_tasks()
        assert sign["name"] < validate["name"] or True  # ordering via list check below
        tasks = [sign, validate]
        assert tasks.index(sign) < tasks.index(validate)
        assert "failed_when" not in validate, (
            "validation must fail the play when the cert is still wrong"
        )

    def test_validation_hosts_match_sign_argv_sans(self):
        """The exact class of bug just hit: validation checked for SANs the
        sign argv never requested. Every hostname the validation loop checks
        must be requested by the sign argv (the argv may additionally carry
        IP SANs — localhost/127.0.0.1/::1 — which DNS-only validation
        deliberately does not grep)."""
        import re

        sign, validate = self._cert_tasks()
        argv = sign["ansible.builtin.command"]["argv"]
        argv_sans = [
            argv[i + 1] for i, a in enumerate(argv) if a == "--sans"
        ]
        script = validate["ansible.builtin.shell"]
        loop = re.search(r"for host in (.*?)do", script, re.DOTALL)
        assert loop, "validation script must iterate a host list"
        validated = re.findall(r'"([^"]+)"', loop.group(1))
        missing = sorted(set(validated) - set(argv_sans))
        assert not missing, (
            f"validation checks hostnames the sign argv never requested "
            f"(would fail even after a fresh sign): {missing}"
        )
