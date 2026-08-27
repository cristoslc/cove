"""Tests for host_vars state management."""

import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import click
import pytest
import yaml

from cove.state import ensure_host_vars
from cove.stateless import detect_hostname, resolve_compose_dir


class TestDetectHostname:
    def test_prefers_macos_local_hostname(self):
        """On macOS, the stable LocalHostName wins over the DHCP-drifted
        kernel hostname (platform.node)."""
        result = MagicMock(returncode=0, stdout="hostname\n", stderr="")
        with patch("cove.stateless.sys.platform", "darwin"), patch(
            "cove.stateless.subprocess.run", return_value=result
        ):
            assert detect_hostname() == "hostname"

    def test_strips_domain_suffix(self):
        result = MagicMock(returncode=0, stdout="hostname.lan\n", stderr="")
        with patch("cove.stateless.sys.platform", "darwin"), patch(
            "cove.stateless.subprocess.run", return_value=result
        ):
            assert detect_hostname() == "hostname"

    def test_scutil_failure_falls_back_to_platform_node(self):
        result = MagicMock(returncode=1, stdout="", stderr="")
        with patch("cove.stateless.sys.platform", "darwin"), patch(
            "cove.stateless.subprocess.run", return_value=result
        ), patch("cove.stateless.platform.node", return_value="testhost.lan"):
            assert detect_hostname() == "testhost"

    def test_scutil_empty_stdout_falls_back_to_platform_node(self):
        result = MagicMock(returncode=0, stdout="   \n", stderr="")
        with patch("cove.stateless.sys.platform", "darwin"), patch(
            "cove.stateless.subprocess.run", return_value=result
        ), patch("cove.stateless.platform.node", return_value="testhost.lan"):
            assert detect_hostname() == "testhost"

    def test_non_macos_uses_platform_node(self):
        with patch("cove.stateless.sys.platform", "linux"), patch(
            "cove.stateless.platform.node", return_value="linuxbox.example.com"
        ):
            assert detect_hostname() == "linuxbox"


class TestEnsureHostVars:
    def test_creates_host_vars_on_first_run(self, tmp_path):
        home = tmp_path
        state_hosts = home / ".config" / "cove" / "state" / "hosts"
        env = {"USER": "testuser"}
        with patch("cove.state.Path.home", return_value=home), patch(
            "cove.state.detect_hostname", return_value="testhost"
        ), patch("cove.state.os.environ", env), patch(
            "cove.state.subprocess.run"
        ) as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
            result = ensure_host_vars()
            assert result == state_hosts / "testhost.yml"
            assert result.exists()
            data = yaml.safe_load(result.read_text())
            assert data["admin_username"] == "testuser"
            assert data["admin_email"] == ""

    def test_uses_git_email(self, tmp_path):
        home = tmp_path
        env = {"USER": "testuser"}
        with patch("cove.state.Path.home", return_value=home), patch(
            "cove.state.detect_hostname", return_value="testhost"
        ), patch("cove.state.os.environ", env), patch(
            "cove.state.subprocess.run"
        ) as mock_run:
            git_result = MagicMock(returncode=0, stdout="gituser@example.com\n", stderr="")
            ts_result = MagicMock(returncode=1, stdout="", stderr="")
            mock_run.side_effect = [git_result, ts_result]
            result = ensure_host_vars()
            data = yaml.safe_load(result.read_text())
            assert data["admin_email"] == "gituser@example.com"

    def test_env_override_takes_precedence(self, tmp_path):
        home = tmp_path
        env = {
            "USER": "shelluser",
            "COVE_ADMIN_USERNAME": "overrideuser",
            "COVE_ADMIN_EMAIL": "override@example.com",
            "COVE_OP_VAULT": "CustomVault",
            "COVE_TS_DNS_NAME": "override.ts.net",
        }
        with patch("cove.state.Path.home", return_value=home), patch(
            "cove.state.detect_hostname", return_value="testhost"
        ), patch("cove.state.os.environ") as mock_environ, patch(
            "cove.state.subprocess.run"
        ) as mock_run:
            mock_environ.get = env.get
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
            result = ensure_host_vars()
            data = yaml.safe_load(result.read_text())
            assert data["admin_username"] == "overrideuser"
            assert data["admin_email"] == "override@example.com"
            assert data["op_vault"] == "CustomVault"
            assert data["ts_dns_name"] == "override.ts.net"

    def test_edit_and_rerun_preserves_values(self, tmp_path):
        home = tmp_path
        host_vars = home / ".config" / "cove" / "state" / "hosts" / "testhost.yml"
        host_vars.parent.mkdir(parents=True)
        host_vars.write_text(yaml.dump({
            "admin_username": "editeduser",
            "admin_email": "edited@example.com",
            "op_vault": "Private",
            "ts_dns_name": "edited.ts.net",
        }))
        env = {"USER": "testuser"}
        with patch("cove.state.Path.home", return_value=home), patch(
            "cove.state.detect_hostname", return_value="testhost"
        ), patch("cove.state.os.environ", env), patch(
            "cove.state.subprocess.run"
        ) as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
            result = ensure_host_vars()
            data = yaml.safe_load(result.read_text())
            assert data["admin_username"] == "editeduser"
            assert data["admin_email"] == "edited@example.com"

    def test_tailscale_dns_detected(self, tmp_path):
        home = tmp_path
        ts_json = '{"Self": {"DNSName": "myhost.example.ts.net."}}'
        env = {"USER": "testuser"}
        with patch("cove.state.Path.home", return_value=home), patch(
            "cove.state.detect_hostname", return_value="testhost"
        ), patch("cove.state.os.environ", env), patch(
            "cove.state.subprocess.run"
        ) as mock_run:
            git_result = MagicMock(returncode=1, stdout="", stderr="")
            ts_result = MagicMock(returncode=0, stdout=ts_json, stderr="")
            mock_run.side_effect = [git_result, ts_result]
            result = ensure_host_vars()
            data = yaml.safe_load(result.read_text())
            assert data["ts_dns_name"] == "myhost.example.ts.net"

    def test_no_tailscale_defaults_localhost(self, tmp_path):
        home = tmp_path
        env = {"USER": "testuser"}
        with patch("cove.state.Path.home", return_value=home), patch(
            "cove.state.detect_hostname", return_value="testhost"
        ), patch("cove.state.os.environ", env), patch(
            "cove.state.subprocess.run"
        ) as mock_run:
            git_result = MagicMock(returncode=1, stdout="", stderr="")
            ts_result = MagicMock(returncode=1, stdout="", stderr="")
            mock_run.side_effect = [git_result, ts_result]
            result = ensure_host_vars()
            data = yaml.safe_load(result.read_text())
            assert data["ts_dns_name"] == "localhost"

    def test_invalid_hostname_raises(self, tmp_path):
        home = tmp_path
        with patch("cove.state.Path.home", return_value=home), patch(
            "cove.state.detect_hostname", return_value="../evil"
        ):
            with pytest.raises(click.ClickException, match="invalid characters"):
                ensure_host_vars()

    def test_invalid_cove_compose_dir_raises(self, tmp_path, monkeypatch):
        bogus = tmp_path / "nope"
        monkeypatch.setenv("COVE_COMPOSE_DIR", str(bogus))
        with pytest.raises(click.ClickException, match="COVE_COMPOSE_DIR"):
            resolve_compose_dir()