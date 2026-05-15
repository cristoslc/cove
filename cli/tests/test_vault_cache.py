"""Tests for vault_cache module."""

from unittest.mock import patch, MagicMock, call

import pytest

from cove import vault_cache


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
