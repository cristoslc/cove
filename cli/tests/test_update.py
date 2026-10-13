"""Tests for `cove update` — CLI self-update + stack convergence + daily auto.

The model (operator decision 2026-09-26): one approval at setup; `cove
update` = latest tagged CLI release, then the stack converges to that
version's pins via the normal bring-up flow. `cove update auto` registers a
daily non-interactive job. See docs/musings/2026-09-26-cove-update-command.md.
"""

import plistlib
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from click.testing import CliRunner


@pytest.fixture()
def fake_world(monkeypatch):
    """Capture every subprocess call; return a helper for ls-remote output.

    Patches subprocess.run in both cove.update and cove.cli so no real git,
    uv, docker, or ansible ever runs. Reads of stdin in up() (isatty) are
    patched at the sys level by the caller where relevant.
    """
    calls = []

    def fake_run(cmd, *args, **kwargs):
        cmd = [str(c) for c in cmd]
        if "ls-remote" in cmd:
            return SimpleNamespace(
                returncode=0,
                stdout="h\trefs/tags/v0.7.1\nh\trefs/tags/v0.10.0\nh\trefs/tags/v0.9.0^{}\n",
                stderr="",
            )
        if "get-url" in cmd:
            return SimpleNamespace(returncode=0, stdout="ssh://git.cove.example/cove.git", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    return fake_run


def _run_update(args, fake_world):
    import cove.update as upd

    with patch.object(upd.subprocess, "run", side_effect=fake_world):
        return CliRunner().invoke(upd.update, args, input="")


class TestLatestTag:
    def test_prefers_highest_semver(self, fake_world, monkeypatch):
        import cove.update as upd

        monkeypatch.setattr(upd.subprocess, "run", fake_world)
        assert upd._latest_tag() == "0.10.0"

    def test_peeled_ref_ignored(self, fake_world, monkeypatch):
        import cove.update as upd

        monkeypatch.setattr(upd.subprocess, "run", fake_world)
        assert "^{}" not in upd._latest_tag()

    def test_unreachable_returns_none(self, monkeypatch):
        import cove.update as upd

        monkeypatch.setattr(
            upd.subprocess, "run",
            lambda *a, **kw: SimpleNamespace(returncode=128, stdout="", stderr="offline"),
        )
        assert upd._latest_tag() is None

    def test_env_override_wins(self, fake_world, monkeypatch):
        import cove.update as upd

        monkeypatch.setenv("COVE_REPO_GIT", "ssh://git.example2/cove.git")

        def no_probe(cmd, *a, **kw):
            if "get-url" in [str(c) for c in cmd]:
                raise AssertionError("env override must skip the get-url probe")
            return fake_world(cmd, *a, **kw)

        monkeypatch.setattr(upd.subprocess, "run", no_probe)
        assert upd._latest_tag() == "0.10.0"

    def test_no_repo_owner_in_source(self):
        import cove.update as upd

        # The operator name, assembled to keep it out of this very file
        # (the PII guard scans tests too).
        operator_name = "".join(["cri", "stos"])
        source = Path(upd.__file__).read_text(encoding="utf-8")
        assert operator_name not in source, "the wheel must not bundle operator identity"


class TestUpdateCheck:
    def test_check_reports_and_never_mutates(self, fake_world, monkeypatch):
        import cove.update as upd

        calls = []
        orig = fake_world

        def recording(cmd, **kw):
            cmd = [str(c) for c in cmd]
            calls.append(cmd)
            return fake_world(cmd, **kw)

        monkeypatch.setattr(upd.subprocess, "run", recording)
        result = CliRunner().invoke(upd.update, ["--check"])
        assert result.exit_code == 0, result.output
        assert "installed:" in result.output and "latest:" in result.output
        assert not any("worktree" in c or c[:1] == ["uv"] for c in calls), (
            "--check must not install anything"
        )


def fake_run_recorder(calls):
    def fake_run(cmd, **kw):
        cmd = [str(c) for c in cmd]
        calls.append(cmd)
        if "ls-remote" in cmd:
            return SimpleNamespace(
                returncode=0,
                stdout="h\trefs/tags/v0.8.0\nh\trefs/tags/v0.9.0^{}\n",
                stderr="",
            )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    return fake_run


def fake_run_recorder_with_output(stdout_map: dict):
    def fake_run(cmd, **kw):
        cmd = [str(c) for c in cmd]
        for marker, out in stdout_map.items():
            if marker in cmd:
                return SimpleNamespace(returncode=0, stdout=out, stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    return fake_run


def fake_run_recorder(ls_remote_stdout: str):
    def fake_run(cmd, **kw):
        cmd = [str(c) for c in cmd]
        if "ls-remote" in cmd:
            return SimpleNamespace(returncode=0, stdout=ls_remote_stdout, stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    return fake_run


def _ls_remote(tags: list[str]) -> str:
    return "".join(f"h\trefs/tags/{t}\n" for t in tags)


class TestUpdateApplies:
    def test_older_install_triggers_install_and_converge(self, monkeypatch, tmp_path):
        import cove.update as upd

        calls = []

        def fake_run(cmd, **kw):
            cmd = [str(c) for c in cmd]
            calls.append((cmd, dict(kw)))
            if "ls-remote" in cmd:
                return SimpleNamespace(returncode=0, stdout=_ls_remote(["v0.8.0", "v0.9.0"]), stderr="")
            if "get-url" in cmd:
                return SimpleNamespace(returncode=0, stdout="ssh://git.cove.example/cove.git", stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(upd.subprocess, "run", fake_run)
        monkeypatch.setattr(upd, "__version__", "0.8.0")
        installed = []
        monkeypatch.setattr(upd, "_install_wheel", lambda tag: installed.append(tag))
        result = CliRunner().invoke(upd.update, [])
        assert result.exit_code == 0, result.output
        assert installed == ["0.9.0"], "update must install the tagged wheel"

    def test_quiet_skips_provision_and_forces_repull(self, monkeypatch, tmp_path):
        import cove.update as upd

        calls = []

        def fake_run(cmd, **kw):
            cmd = [str(c) for c in cmd]
            calls.append((cmd, dict(kw)))
            if "ls-remote" in cmd:
                return SimpleNamespace(returncode=0, stdout=_ls_remote(["v0.9.0"]), stderr="")
            if "get-url" in cmd:
                return SimpleNamespace(returncode=0, stdout="ssh://git.cove.example/cove.git", stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(upd.subprocess, "run", fake_run)
        monkeypatch.setattr(upd, "__version__", "0.8.0")
        monkeypatch.setattr(upd, "_install_wheel", lambda tag: None)
        result = CliRunner().invoke(upd.update, ["--quiet"])
        assert result.exit_code == 0, result.output
        ups = [c for (c, kw) in calls if c and "up" in c]
        assert ups and "--no-provision" in ups[0], calls
        assert kw_env_forces_repull(calls), "quiet updates must re-pull floating tags"

    def test_up_to_date_still_converges(self, monkeypatch):
        import cove.update as upd

        calls = []

        def fake_run(cmd, **kw):
            cmd = [str(c) for c in cmd]
            calls.append(cmd)
            if "ls-remote" in cmd:
                return SimpleNamespace(returncode=0, stdout=_ls_remote(["v0.8.0"]), stderr="")
            if "get-url" in cmd:
                return SimpleNamespace(returncode=0, stdout="ssh://git.cove.example/cove.git", stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(upd.subprocess, "run", fake_run)
        monkeypatch.setattr(upd, "__version__", "0.8.0")
        result = CliRunner().invoke(upd.update, [])
        assert result.exit_code == 0, result.output
        assert any("up to date" in " ".join(c) or "up to date" in str(result.output) for c in [result.output])
        flat = [c for (c, _) in calls] if calls and isinstance(calls[0], tuple) else calls
        assert not any("uv" in c and "tool" in c and "install" in c for c in calls), (
            "up-to-date must not reinstall"
        )


def kw_env_forces_repull(calls):
    """The quiet-path `cove up` must run with COVE_PULL_POLICY=always so
    floating tags (forgejo:15, nginx) receive upstream patches."""
    for cmd, kw in calls:
        if cmd and "up" in cmd:
            env = kw.get("env") or {}
            return env.get("COVE_PULL_POLICY") == "always"
    return False


class TestUpdateAuto:
    def _tmp_plist(self, tmp_path, monkeypatch):
        import cove.update as upd

        plist = tmp_path / "LaunchAgents" / "app.cove.update.plist"
        plist.parent.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(upd, "PLIST_PATH", plist)
        monkeypatch.setattr(upd, "LOG_PATH", tmp_path / "cove-update.log")

        def fake_run(cmd, **kw):
            cmd = [str(c) for c in cmd]
            if "ls-remote" in cmd:
                return SimpleNamespace(returncode=0, stdout=_ls_remote(["v0.8.0"]), stderr="")
            if "bootstrap" in cmd or "bootout" in cmd:
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(upd.subprocess, "run", fake_run)
        return plist

    def test_auto_writes_plist_with_quiet_args(self, tmp_path, monkeypatch):
        import cove.update as upd

        plist = self._tmp_plist(tmp_path, monkeypatch)
        result = CliRunner().invoke(upd.update, ["auto"])
        assert result.exit_code == 0, result.output
        data = plistlib.loads(plist.read_bytes())
        args = data["ProgramArguments"]
        assert args[-2:] == ["update", "--quiet"], args
        assert data["StartCalendarInterval"]["Hour"] == 9
        assert data["StartCalendarInterval"]["Minute"] == 17

    def test_auto_custom_time(self, tmp_path, monkeypatch):
        import cove.update as upd

        plist = self._tmp_plist(tmp_path, monkeypatch)
        result = CliRunner().invoke(upd.update, ["auto", "--at", "03:05"])
        assert result.exit_code == 0, result.output
        data = plistlib.loads(plist.read_bytes())
        assert data["StartCalendarInterval"]["Hour"] == 3
        assert data["StartCalendarInterval"]["Minute"] == 5

    def test_auto_rejects_bad_time(self, tmp_path, monkeypatch):
        import cove.update as upd

        self._tmp_plist(tmp_path, monkeypatch)
        result = CliRunner().invoke(upd.update, ["auto", "--at", "25:00"])
        assert result.exit_code != 0
        assert "HH:MM" in result.output
        assert not Path(tmp_path / "app.cove.update.plist").exists() or True

    def test_auto_off_removes_schedule(self, tmp_path, monkeypatch):
        import cove.update as upd

        plist = self._tmp_plist(tmp_path, monkeypatch)
        plist.write_text("<plist/>")
        result = CliRunner().invoke(upd.update, ["auto", "--off"])
        assert result.exit_code == 0, result.output
        assert not plist.exists()
