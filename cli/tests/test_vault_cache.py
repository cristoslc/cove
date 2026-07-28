"""Tests for vault_cache module."""

import ssl
from unittest.mock import patch, MagicMock, call

import pytest

from cove import vault_cache


class TestVaultAddrDefault:
    """RED: the CLI default must point at the reachable ingress, not an
    unpublished port on the host loopback."""

    def test_default_addr_is_vault_cove_https(self):
        assert vault_cache.VAULT_ADDR_DEFAULT == "https://vault.cove.local/"

    def test_vault_addr_respects_env_override(self, monkeypatch):
        monkeypatch.setenv("VAULT_ADDR", "http://override.example:8200")
        assert vault_cache._vault_addr() == "http://override.example:8200"

    def test_vault_addr_falls_back_to_default_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("VAULT_ADDR", raising=False)
        assert vault_cache._vault_addr() == "https://vault.cove.local/"


class TestVaultPutOpRef:
    """RED: vault_put_op_ref must fetch from 1Password and write to Vault when uncached."""

    def test_put_fetches_from_op_and_writes_to_vault_when_uncached(self):
        op_ref = "op://Private/Test Item/password"
        secret_value = "s3cret-password"

        with patch("cove.vault_cache.local_cache.get", return_value=None), \
             patch("cove.vault_cache.vault_get_cached", return_value=None), \
             patch("cove.vault_cache._op_read", return_value=secret_value) as mock_op_read, \
             patch("cove.vault_cache._vault_write") as mock_vault_write, \
             patch("cove.vault_cache.local_cache.put") as mock_local_put:

            result = vault_cache.vault_put_op_ref(op_ref, force_refresh=False)

            mock_op_read.assert_called_once_with(op_ref)
            mock_vault_write.assert_called_once_with(op_ref, secret_value)
            mock_local_put.assert_called_once_with(op_ref, secret_value)
            assert result == secret_value

    def test_put_writes_op_ref_as_external_reference_to_vault(self):
        op_ref = "op://Private/My Vault/api-key"
        secret_value = "sk-abcdef123"

        with patch("cove.vault_cache.local_cache.get", return_value=None), \
             patch("cove.vault_cache.vault_get_cached", return_value=None), \
             patch("cove.vault_cache._op_read", return_value=secret_value), \
             patch("cove.vault_cache._vault_write") as mock_vault_write:

            vault_cache.vault_put_op_ref(op_ref, force_refresh=False)

            mock_vault_write.assert_called_once_with(op_ref, secret_value)

    def test_put_force_refresh_skips_caches(self):
        op_ref = "op://Private/Test Item/token"
        secret_value = "fresh-token-999"

        with patch("cove.vault_cache.local_cache.get") as mock_local_get, \
             patch("cove.vault_cache.vault_get_cached") as mock_vault_get, \
             patch("cove.vault_cache._op_read", return_value=secret_value), \
             patch("cove.vault_cache._vault_write"), \
             patch("cove.vault_cache.local_cache.put"):

            vault_cache.vault_put_op_ref(op_ref, force_refresh=True)

            mock_local_get.assert_not_called()
            mock_vault_get.assert_not_called()

    def test_put_returns_local_cached_value_without_op_call(self):
        op_ref = "op://Private/Test Item/host"
        cached_value = "pre-cached-host"

        with patch("cove.vault_cache.local_cache.get", return_value=cached_value), \
             patch("cove.vault_cache._op_read") as mock_op_read, \
             patch("cove.vault_cache._vault_write") as mock_vault_write:

            result = vault_cache.vault_put_op_ref(op_ref, force_refresh=False)

            mock_op_read.assert_not_called()
            mock_vault_write.assert_not_called()
            assert result == cached_value

    def test_put_falls_back_to_vault_cache_before_op(self):
        op_ref = "op://Private/Test Item/username"
        vault_value = "vault-cached-user"

        with patch("cove.vault_cache.local_cache.get", return_value=None), \
             patch("cove.vault_cache.vault_get_cached", return_value=vault_value) as mock_vault_get, \
             patch("cove.vault_cache._op_read") as mock_op_read, \
             patch("cove.vault_cache._vault_write") as mock_vault_write, \
             patch("cove.vault_cache.local_cache.put"):

            result = vault_cache.vault_put_op_ref(op_ref, force_refresh=False)

            mock_vault_get.assert_called_once_with(op_ref)
            mock_op_read.assert_not_called()
            mock_vault_write.assert_not_called()
            assert result == vault_value

    def test_put_raises_on_op_read_failure(self):
        op_ref = "op://Private/Bad Vault/missing-field"

        with patch("cove.vault_cache.local_cache.get", return_value=None), \
             patch("cove.vault_cache.vault_get_cached", return_value=None), \
             patch("cove.vault_cache._op_read", side_effect=RuntimeError("op failed")):

            with pytest.raises(RuntimeError, match="op failed"):
                vault_cache.vault_put_op_ref(op_ref, force_refresh=False)


class TestVaultTLSContext:
    """RED: requests to https://vault.cove/ must verify against the cove root CA,
    not the system trust store (which on a fresh box may not have it installed)."""

    def test_ssl_context_loads_cove_root_ca(self, monkeypatch):
        import tempfile
        from pathlib import Path

        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID
        from datetime import datetime, timedelta, timezone

        key = ec.generate_private_key(ec.SECP256R1())
        subject = issuer = x509.Name(
            [x509.NameAttribute(NameOID.COMMON_NAME, "test-cove-root-ca")]
        )
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.now(timezone.utc) - timedelta(days=1))
            .not_valid_after(datetime.now(timezone.utc) + timedelta(days=1))
            .sign(key, hashes.SHA256())
        )
        ca_bytes = cert.public_bytes(serialization.Encoding.PEM)

        with tempfile.TemporaryDirectory() as d:
            cafile = Path(d) / "rootCA.pem"
            cafile.write_bytes(ca_bytes)
            monkeypatch.setattr(
                "cove.vault_cache._cove_ca_path", lambda: cafile
            )
            ctx = vault_cache._vault_ssl_context()
            assert isinstance(ctx, ssl.SSLContext)
            assert ctx.verify_mode == ssl.CERT_REQUIRED

    def test_vault_request_passes_ssl_context_to_urlopen(self, monkeypatch):
        monkeypatch.setenv("VAULT_ADDR", "https://vault.cove")
        monkeypatch.setattr("cove.vault_cache._vault_token", lambda: "tok")
        monkeypatch.setattr(
            "cove.vault_cache._vault_ssl_context",
            lambda: ssl.create_default_context(),
        )
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = mock_urlopen.return_value.__enter__.return_value
            mock_resp.status = 200
            mock_resp.read.return_value = b'{"data": {"data": {"value": "v"}}}'
            vault_cache.vault_get_cached("op://Private/Item/field")
            args, kwargs = mock_urlopen.call_args
            assert "context" in kwargs, "urlopen must be called with an SSL context"
            assert isinstance(kwargs["context"], ssl.SSLContext)
