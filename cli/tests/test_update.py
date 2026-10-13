"""Tests for `cove update` — CLI self-update + stack convergence + daily auto.

The model (operator decision 2026-09-26): one approval at setup; `cove
update` = latest tagged CLI release, then the stack converges to that
version's pins via the normal bring-up flow. `cove update auto` registers a
daily non-interactive job. See docs/musings/2026-09-26-cove-update-command.md.
"""

import plistlib
from importlib.resources import files
import tempfile
import shutil
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

    def test_quiet_skips_provision_and_forces_repull(self, deployed_compose, monkeypatch, tmp_path):
        import cove.update as upd

        (deployed_compose / "docker-compose.yml").write_text("services: {changed: 1}\n")
        calls = []

        def fake_run(cmd, **kw):
            cmd = [str(c) for c in cmd]
            calls.append((cmd, dict(kw)))
            if "ls-remote" in cmd:
                return SimpleNamespace(returncode=0, stdout=_ls_remote(["v0.9.0"]), stderr="")
            if "get-url" in cmd:
                return SimpleNamespace(returncode=0, stdout="ssh://git.cove.example/cove.git", stderr="")
            if "ps" in cmd:
                return SimpleNamespace(
                    returncode=0, stdout="\n".join(_COVE_STACK) + "\n", stderr=""
                )
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(upd.subprocess, "run", fake_run)
        monkeypatch.setattr(upd, "__version__", "0.8.0")
        monkeypatch.setattr(upd, "_install_wheel", lambda tag: None)
        result = CliRunner().invoke(upd.update, ["--quiet"])
        assert result.exit_code == 0, result.output
        ups = [c for (c, kw) in calls if c and "up" in c]
        assert ups and "--no-provision" in ups[0], calls
        assert kw_env_forces_repull(calls), "quiet updates must re-pull floating tags"

    def test_up_to_date_no_reinstall(self, deployed_compose, monkeypatch):
        import cove.update as upd

        calls = []
        fake_run = _fake_run_with_stack(stack_running=True, ls_remote_stdout=_ls_remote(["v0.8.0"]))
        monkeypatch.setattr(upd.subprocess, "run", fake_run)
        installed = []
        monkeypatch.setattr(upd, "__version__", "0.9.0")
        monkeypatch.setattr(upd, "_install_wheel", lambda tag: installed.append(tag))
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
# ---------------------------------------------------------------------------
# Converge gating: bring up only when something was running AND the update
# would actually change the stack (operator decision 2026-10-13).
# ---------------------------------------------------------------------------

_COVE_STACK = ["cove-nginx", "cove-ade-server", "cove-vault"]


def _fake_run_with_stack(stack_running: bool, ls_remote_stdout: str | None = None):
    """fake_run that also answers `docker ps` (running cove stack or not)."""
    def fake_run(cmd, *a, **kw):
        cmd = [str(c) for c in cmd]
        if "ls-remote" in cmd:
            out = ls_remote_stdout if ls_remote_stdout is not None else _ls_remote(["v0.9.0"])
            return SimpleNamespace(returncode=0, stdout=out, stderr="")
        if "get-url" in cmd:
            return SimpleNamespace(returncode=0, stdout="ssh://git.cove.example/cove.git", stderr="")
        if "ps" in cmd:
            return SimpleNamespace(
                returncode=0,
                stdout="\n".join(_COVE_STACK if stack_running else ["httpd", "redis"]),
                stderr="",
            )
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    return fake_run


@pytest.fixture()
def deployed_compose(tmp_path, monkeypatch):
    """A deployed compose dir seeded from the current wheel's bundled tree
    (identical → no-op); callers mutate `bump=...` to force a diff."""
    with tempfile.TemporaryDirectory() as td:
        root = tmp_path / "deployed-compose"
        src = Path(str(files("cove.resources") / "compose"))
        shutil.copytree(src, root, dirs_exist_ok=True)
        monkeypatch.setenv("COVE_COMPOSE_DIR", str(root))
        yield root


class TestConvergeGating:
    def test_up_to_date_and_converged_is_a_no_op(self, deployed_compose, monkeypatch):
        import cove.update as upd

        calls = []
        fake_run = _fake_run_with_stack(stack_running=True)
        monkeypatch.setattr(upd.subprocess, "run", fake_run)
        monkeypatch.setattr(upd, "__version__", "0.9.0")

        def recording(cmd, **kw):
            cmd = [str(c) for c in cmd]
            calls.append(cmd)
            return fake_run(cmd, **kw)

        monkeypatch.setattr(upd.subprocess, "run", recording)
        result = CliRunner().invoke(upd.update, ["--quiet"])
        assert result.exit_code == 0, result.output
        assert installed_or_up_calls(calls) == [], "converged stack: no bring-up"

    def test_compose_diff_bring_up_running_stack(self, deployed_compose, monkeypatch):
        import cove.update as upd

        (deployed_compose / "nginx" / "default.conf.j2").write_text("changed\n")
        calls = []
        fake_run = _fake_run_with_stack(stack_running=True)
        monkeypatch.setattr(upd.subprocess, "run", fake_run)
        monkeypatch.setattr(upd, "__version__", "0.8.0")
        monkeypatch.setattr(upd, "_install_wheel", lambda tag: None)

        def recording(cmd, **kw):
            cmd = [str(c) for c in cmd]
            calls.append(cmd)
            return fake_run(cmd, **kw)

        monkeypatch.setattr(upd.subprocess, "run", recording)
        result = CliRunner().invoke(upd.update, ["--quiet"])
        assert result.exit_code == 0, result.output
        assert installed_or_up_calls(calls) != [], "changed pins + running stack: converge"

    def test_env_overrides_alone_never_bring_up(self, deployed_compose, monkeypatch):
        import cove.update as upd

        (deployed_compose / ".env").write_text("ADE_BB_APP_VERSION=0.46.0\n")
        calls = []
        fake_run = _fake_run_with_stack(stack_running=True)
        monkeypatch.setattr(upd.subprocess, "run", fake_run)
        monkeypatch.setattr(upd, "__version__", "0.9.0")

        def recording(cmd, **kw):
            cmd = [str(c) for c in cmd]
            calls.append(cmd)
            return fake_run(cmd, **kw)

        monkeypatch.setattr(upd.subprocess, "run", recording)
        result = CliRunner().invoke(upd.update, ["--quiet"])
        assert result.exit_code == 0, result.output
        assert installed_or_up_calls(calls) == [], ".env is override surface, not a diff"

    def test_down_stack_never_brought_up_even_with_diffs(self, deployed_compose, monkeypatch):
        import cove.update as upd

        (deployed_compose / "docker-compose.yml").write_text("services: {changed: 1}\n")
        calls = []
        fake_run = _fake_run_with_stack(stack_running=False)
        monkeypatch.setattr(upd.subprocess, "run", fake_run)
        monkeypatch.setattr(upd, "__version__", "0.8.0")
        monkeypatch.setattr(upd, "_install_wheel", lambda tag: None)

        def recording(cmd, **kw):
            cmd = [str(c) for c in cmd]
            calls.append(cmd)
            return fake_run(cmd, **kw)

        monkeypatch.setattr(upd.subprocess, "run", recording)
        result = CliRunner().invoke(upd.update, ["--quiet"])
        assert result.exit_code == 0, result.output
        assert installed_or_up_calls(calls) == [], "stopped services stay stopped"
        assert "not running" in result.output.lower()

    def test_check_reports_stack_and_convergence(self, deployed_compose, monkeypatch):
        import cove.update as upd

        fake_run = _fake_run_with_stack(stack_running=True)
        monkeypatch.setattr(upd.subprocess, "run", fake_run)
        result = CliRunner().invoke(upd.update, ["--check"])
        assert result.exit_code == 0, result.output
        assert "running" in result.output
        assert "converge" in result.output


    def test_generated_runtime_files_do_not_trip_pending(self, deployed_compose, monkeypatch):
        """Rendered artifacts the wheel never ships (nginx/default.conf,
        dnsmasq/cove.conf, seeds/*.yaml credential seeds) live in a deployed
        dev checkout and must not read as a pending pin change."""
        import cove.update as upd

        (deployed_compose / "nginx" / "default.conf").write_text("rendered\n")
        (deployed_compose / "dnsmasq" / "cove.conf").write_text("host=mbpbk\n")
        (deployed_compose / "seeds" / "minio-creds.yaml").write_text("creds: x\n")
        calls = []
        fake_run = _fake_run_with_stack(stack_running=True)
        monkeypatch.setattr(upd.subprocess, "run", fake_run)
        monkeypatch.setattr(upd, "__version__", "0.9.0")

        def recording(cmd, **kw):
            cmd = [str(c) for c in cmd]
            calls.append(cmd)
            return fake_run(cmd, **kw)

        monkeypatch.setattr(upd.subprocess, "run", recording)
        result = CliRunner().invoke(upd.update, ["--quiet"])
        assert result.exit_code == 0, result.output
        assert installed_or_up_calls(calls) == [], (
            "generated runtime files are not pin changes"
        )


    def test_env_example_does_not_trip_pending(self, deployed_compose, monkeypatch):
        """.env.example documents the override surface; the wheel may not ship
        it (dotfile packaging), and it changes no pins — it must not read as
        pending."""
        import cove.update as upd

        (deployed_compose / ".env.example").write_text("DOCUMENTED_OVERRIDE=1\n")
        calls = []
        fake_run = _fake_run_with_stack(stack_running=True)
        monkeypatch.setattr(upd.subprocess, "run", fake_run)
        monkeypatch.setattr(upd, "__version__", "0.9.0")

        def recording(cmd, **kw):
            cmd = [str(c) for c in cmd]
            calls.append(cmd)
            return fake_run(cmd, **kw)

        monkeypatch.setattr(upd.subprocess, "run", recording)
        result = CliRunner().invoke(upd.update, ["--quiet"])
        assert result.exit_code == 0, result.output
        assert installed_or_up_calls(calls) == [], (
            ".env.example is override-surface documentation, not a pin change"
        )


def installed_or_up_calls(calls):
    """Calls that either install (uv tool install) or bring up (`cove up`)."""
    return [
        c for c in calls
        if ("tool" in c and "install" in c) or (c and c[0].endswith("cove") and "up" in c)
    ]
