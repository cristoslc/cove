"""Tests for passwordless sudo (`cove sudo`)."""

import getpass
from unittest.mock import patch

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


class TestOperatorUsername:
    """The NOPASSWD grant must target the invoking operator, never root."""

    def test_defaults_to_current_user(self, monkeypatch):
        monkeypatch.delenv("SUDO_USER", raising=False)
        assert sudoers._operator_username() == getpass.getuser()

    def test_uses_sudo_user_when_running_under_sudo(self, monkeypatch):
        monkeypatch.setattr(sudoers.os, "geteuid", lambda: 0)
        monkeypatch.setenv("SUDO_USER", "alice")
        assert sudoers._operator_username() == "alice"

    def test_falls_back_to_current_user_for_real_root(self, monkeypatch):
        monkeypatch.setattr(sudoers.os, "geteuid", lambda: 0)
        monkeypatch.delenv("SUDO_USER", raising=False)
        monkeypatch.setattr(sudoers.getpass, "getuser", lambda: "root")
        assert sudoers._operator_username() == "root"

    def test_rendered_grant_targets_sudo_user_not_root(self, monkeypatch):
        monkeypatch.setattr(sudoers.os, "geteuid", lambda: 0)
        monkeypatch.setenv("SUDO_USER", "alice")
        monkeypatch.setattr(sudoers.getpass, "getuser", lambda: "root")
        rendered = sudoers._rendered_sudoers()
        assert "alice ALL=(ALL) NOPASSWD: ALL" in rendered
        assert "\nroot ALL=" not in rendered


class _Proc:
    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _patch_sudo_list(monkeypatch, returncode, stdout="", stderr=""):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _Proc(returncode, stdout, stderr)

    monkeypatch.setattr(sudoers.subprocess, "run", fake_run)
    return calls


class TestPasswordlessSudoOk:
    """The check is functional: `sudo -n -l` output must name NOPASSWD: ALL.

    /etc/sudoers.d/cove is root-owned 0440, so an unprivileged `visudo -c -f`
    always fails with EACCES — the old file-based check could never return
    True for a non-root operator, which is why `cove up` kept prompting for a
    BECOME password even with the drop-in installed.
    """

    def test_true_when_sudo_lists_nopasswd_all(self, monkeypatch):
        calls = _patch_sudo_list(
            monkeypatch,
            0,
            stdout=(
                "User alice may run the following commands on devbox:\n"
                "    (ALL) NOPASSWD: ALL\n"
            ),
        )
        assert sudoers.passwordless_sudo_ok() is True
        assert calls == [["sudo", "-n", "-l"]]

    def test_false_when_sudo_requires_password(self, monkeypatch):
        _patch_sudo_list(monkeypatch, 1, stderr="sudo: a password is required\n")
        assert sudoers.passwordless_sudo_ok() is False

    def test_false_when_listing_lacks_nopasswd(self, monkeypatch):
        # A cached sudo timestamp lets `sudo -n` succeed for password grants
        # too; the listing must name NOPASSWD: ALL, not just exit 0.
        _patch_sudo_list(
            monkeypatch,
            0,
            stdout=(
                "User alice may run the following commands on devbox:\n"
                "    (ALL : ALL) ALL\n"
            ),
        )
        assert sudoers.passwordless_sudo_ok() is False

    def test_false_when_nopasswd_grant_is_scoped(self, monkeypatch):
        _patch_sudo_list(
            monkeypatch,
            0,
            stdout=(
                "User alice may run the following commands on devbox:\n"
                "    (root) NOPASSWD: /usr/bin/docker\n"
            ),
        )
        assert sudoers.passwordless_sudo_ok() is False


class TestSudoStatusCommand:
    def test_status_reports_not_installed(self, monkeypatch):
        monkeypatch.setattr(sudoers, "passwordless_sudo_ok", lambda: False)
        runner = CliRunner()
        result = runner.invoke(sudoers.sudo, ["status"])
        assert result.exit_code == 0
        assert "NOT in place" in result.output
        assert "`cove sudo setup`" in result.output

    def test_status_reports_installed(self, monkeypatch):
        monkeypatch.setattr(sudoers, "passwordless_sudo_ok", lambda: True)
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

    def test_setup_under_sudo_grants_operator_without_password_prompt(self, monkeypatch):
        """`sudo cove sudo setup` runs as root: no password prompt, and the
        grant targets SUDO_USER, not root (the bug that silently dropped the
        operator's passwordless sudo)."""
        monkeypatch.setattr(sudoers.os, "geteuid", lambda: 0)
        monkeypatch.setenv("SUDO_USER", "alice")
        runner_run = _RunOk()

        def _must_not_prompt(*args, **kwargs):
            raise AssertionError("setup must not prompt for a password when already root")

        with patch("cove.sudoers.getpass.getpass", _must_not_prompt), patch(
            "cove.sudoers.subprocess.run", runner_run
        ):
            result = CliRunner().invoke(sudoers.sudo, ["setup"])
        assert result.exit_code == 0, result.output
        assert len(runner_run.calls) == 2
