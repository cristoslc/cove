"""Tests for passwordless sudo (`cove sudo`)."""

import getpass
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from cove import sudoers


class TestRenderedSudoers:
    def test_replaces_username_placeholder(self):
        rendered = sudoers._rendered_sudoers()
        assert getpass.getuser() in rendered
        assert "YOUR_USERNAME" not in rendered

    def test_rendered_sudoers_has_nopasswd_grant(self):
        rendered = sudoers._rendered_sudoers()
        assert "NOPASSWD: ALL" in rendered


class TestPasswordlessSudoOk:
    def test_false_when_dropin_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sudoers, "SUDOERS_PATH", tmp_path / "nope")
        assert sudoers.passwordless_sudo_ok() is False

    def test_true_when_dropin_valid(self, tmp_path, monkeypatch):
        path = tmp_path / "cove"
        path.write_text("cristos ALL=(ALL) NOPASSWD: ALL\n")
        monkeypatch.setattr(sudoers, "SUDOERS_PATH", path)
        assert sudoers.passwordless_sudo_ok() is True

    def test_false_when_dropin_invalid(self, tmp_path, monkeypatch):
        path = tmp_path / "cove"
        path.write_text("this is not a sudoers rule\n")
        monkeypatch.setattr(sudoers, "SUDOERS_PATH", path)
        assert sudoers.passwordless_sudo_ok() is False


class TestSudoStatusCommand:
    def test_status_reports_not_installed(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sudoers, "SUDOERS_PATH", tmp_path / "nope")
        runner = CliRunner()
        result = runner.invoke(sudoers.sudo, ["status"])
        assert result.exit_code == 0
        assert "NOT in place" in result.output
        assert "`cove sudo setup`" in result.output

    def test_status_reports_installed(self, tmp_path, monkeypatch):
        path = tmp_path / "cove"
        path.write_text("cristos ALL=(ALL) NOPASSWD: ALL\n")
        monkeypatch.setattr(sudoers, "SUDOERS_PATH", path)
        runner = CliRunner()
        result = runner.invoke(sudoers.sudo, ["status"])
        assert result.exit_code == 0
        assert "Passwordless sudo is in place" in result.output


class _RunOk:
    """subprocess.run stub returning a successful result."""
    returncode = 0
    stdout = ""
    stderr = ""

    def __init__(self):
        self.calls = []

    def __call__(self, cmd, **kwargs):
        self.calls.append(cmd)
        return self


class _RunFail:
    returncode = 1
    stdout = "syntax error"
    stderr = ""

    def __init__(self):
        self.calls = []

    def __call__(self, cmd, **kwargs):
        self.calls.append(cmd)
        return self

class TestSudoSetupCommand:
    def test_setup_validates_before_install_and_stages_move(self, tmp_path, monkeypatch):
        """setup must run visudo -c -sf on the rendered file, then install via
        a staging step (cp to *.tmp, chmod 440, visudo -c -f *.tmp, mv)."""
        runner_run = _RunOk()
        with patch("cove.sudoers.getpass.getpass", return_value="secret"), patch(
            "cove.sudoers.subprocess.run", runner_run
        ):
            result = CliRunner().invoke(sudoers.sudo, ["setup"])
        assert result.exit_code == 0, result.output
        assert len(runner_run.calls) == 2, (
            f"expected visudo precheck + sudo install, got: {runner_run.calls}"
        )
        precheck, install = runner_run.calls
        assert precheck[0] == "visudo" and "-sf" in precheck
        assert install[0] == "sudo"
        sh_cmd = next(a for a in install if "mv" in str(a))
        assert f"{sudoers.SUDOERS_PATH}.tmp" in str(sh_cmd)
        assert "chmod 440" in str(sh_cmd)
        assert f"visudo -c -f {sudoers.SUDOERS_PATH}.tmp" in str(sh_cmd)

    def test_setup_aborts_without_installing_on_failed_validation(self, tmp_path, monkeypatch):
        runner_run = _RunFail()
        with patch("cove.sudoers.getpass.getpass", return_value="secret"), patch(
            "cove.sudoers._rendered_sudoers", return_value="bogus !invalid"
        ), patch("cove.sudoers.subprocess.run", runner_run):
            result = CliRunner().invoke(sudoers.sudo, ["setup"])
        assert result.exit_code != 0, "invalid sudoers must abort setup"
        assert "failed validation" in result.output
        assert not any(c[0] == "sudo" for c in runner_run.calls), (
            "setup must not invoke sudo when the rendered file fails visudo"
        )