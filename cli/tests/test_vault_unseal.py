"""Tests for vault_unseal module."""

import io
import json
from unittest.mock import patch

import pytest

from cove import vault_unseal


class TestVaultHealth:
    def test_healthy_parsed_correctly(self):
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_response = mock_urlopen.return_value.__enter__.return_value
            mock_response.read.return_value = json.dumps(
                {"initialized": True, "sealed": False, "version": "1.20.4"}
            ).encode()
            mock_response.status = 200

            health = vault_unseal.vault_health()
            assert health["initialized"] is True
            assert health["sealed"] is False

    def test_sealed_returns_data(self):
        with patch("urllib.request.urlopen") as mock_urlopen:
            import urllib.error

            err = urllib.error.HTTPError(
                "http://127.0.0.1:8200/v1/sys/health",
                503,
                "Sealed",
                {},
                io.BytesIO(json.dumps({"initialized": True, "sealed": True}).encode()),
            )
            mock_urlopen.side_effect = err

            health = vault_unseal.vault_health()
            assert health["initialized"] is True
            assert health["sealed"] is True

    def test_unreachable_raises(self):
        with patch("urllib.request.urlopen") as mock_urlopen:
            import urllib.error

            mock_urlopen.side_effect = urllib.error.URLError("Connection refused")

            with pytest.raises(RuntimeError, match="unreachable"):
                vault_unseal.vault_health()


class TestVaultPost:
    def test_urlerror_raises(self):
        with patch("urllib.request.urlopen") as mock_urlopen:
            import urllib.error

            mock_urlopen.side_effect = urllib.error.URLError("Connection refused")

            with pytest.raises(RuntimeError, match="unreachable"):
                vault_unseal._vault_post("v1/sys/unseal", {"key": "test"})


class TestEnsureUnsealed:
    def test_raises_if_not_initialized(self):
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_response = mock_urlopen.return_value.__enter__.return_value
            mock_response.read.return_value = json.dumps(
                {"initialized": False, "sealed": True}
            ).encode()
            mock_response.status = 501

            with pytest.raises(RuntimeError, match="not initialized"):
                vault_unseal.ensure_unsealed()

    def test_returns_health_if_already_unsealed(self):
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_response = mock_urlopen.return_value.__enter__.return_value
            mock_response.read.return_value = json.dumps(
                {"initialized": True, "sealed": False}
            ).encode()
            mock_response.status = 200

            health = vault_unseal.ensure_unsealed()
            assert health["sealed"] is False

    def test_unseals_when_sealed(self):
        call_count = [0]

        def urlopen_side_effect(req, **kw):
            call_count[0] += 1
            call = call_count[0]

            class MockResp:
                status = 200

                def read(self):
                    if call == 1:
                        return json.dumps({"initialized": True, "sealed": True}).encode()
                    elif call <= 5:
                        return json.dumps({}).encode()
                    elif call == 6:
                        return json.dumps(
                            {"initialized": True, "sealed": False}
                        ).encode()

                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return None

            return MockResp()

        with patch(
            "urllib.request.urlopen", side_effect=urlopen_side_effect
        ), patch("subprocess.run") as mock_subprocess:
            mock_proc = mock_subprocess.return_value
            mock_proc.returncode = 0
            mock_proc.stdout = "fake-unseal-key\n"

            health = vault_unseal.ensure_unsealed()
            assert health["sealed"] is False
            assert call_count[0] >= 5


class TestKeystoreRead:
    def test_macos_reads_from_security(self):
        with patch("platform.system", return_value="Darwin"), patch(
            "subprocess.run"
        ) as mock_run:
            mock_proc = mock_run.return_value
            mock_proc.returncode = 0
            mock_proc.stdout = "secret-value\n"

            result = vault_unseal._read_keystore("cove/vault/unseal-1")
            assert result == "secret-value"

    def test_linux_reads_from_secret_tool(self):
        with patch("platform.system", return_value="Linux"), patch(
            "subprocess.run"
        ) as mock_run:
            mock_proc = mock_run.return_value
            mock_proc.returncode = 0
            mock_proc.stdout = "secret-value\n"

            result = vault_unseal._read_keystore("cove/vault/unseal-1")
            assert result == "secret-value"

    def test_raises_on_failure(self):
        with patch("platform.system", return_value="Darwin"), patch(
            "subprocess.run"
        ) as mock_run:
            mock_proc = mock_run.return_value
            mock_proc.returncode = 1
            mock_proc.stderr = "Item not found\n"

            with pytest.raises(RuntimeError, match="Item not found"):
                vault_unseal._read_keystore("cove/vault/unseal-1")
