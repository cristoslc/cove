"""Tests for `cove serve` — login-time stack autostart.

The agent is a `RunAtLoad` LaunchAgent (label `app.cove.serve`) mirroring
`cove update auto`: render a plist, `launchctl bootstrap` it, `launchctl
bootout` on stop. Its payload (`cove serve run`, hidden) probes the Docker
runtime, converges with `cove up --no-provision --non-interactive`, then unseals
Vault. See docs/musings/cove-serve-autostart.md (Decided 2026-10-22).

Every test mocks `subprocess.run`: no real launchctl bootstrap/bootout and no
container operations run here. The operator runs `cove serve start` for the
first real activation.
"""

import os
import plistlib
import shutil
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from click.testing import CliRunner


@pytest.fixture()
def serve_world(tmp_path, monkeypatch):
    """Isolate the plist/log paths and capture every subprocess call.

    Returns a namespace with:
    - `plist`: the patched PLIST_PATH
    - `calls`: list of (argv, kwargs) for every subprocess.run
    - `state`: mutable flags the fakes consult (`docker_up`, `colima_started`,
      `up_rc`, `loaded`)
    """
    import cove.serve as srv
    import cove.vault as vlt

    plist = tmp_path / "LaunchAgents" / "app.cove.serve.plist"
    monkeypatch.setattr(srv, "PLIST_PATH", plist)
    monkeypatch.setattr(srv, "LOG_PATH", tmp_path / "cove-serve.log")
    monkeypatch.setattr(srv, "_cove_bin", lambda: "cove")
    # No real backoff between Docker probes.
    monkeypatch.setattr(srv.time, "sleep", lambda _s: None)

    state = SimpleNamespace(
        docker_up=True, colima_started=False, up_rc=0, loaded=False,
    )
    calls: list = []
    unseals: list = []

    def fake_unseal():
        unseals.append(True)
        return {"sealed": False}

    # Default: Vault unseal succeeds. Tests that need a failure override
    # cove.vault.ensure_unsealed (the real unseal_or_warn then warns).
    monkeypatch.setattr(vlt, "ensure_unsealed", fake_unseal)

    def fake_run(cmd, *a, **kw):
        argv = [str(c) for c in cmd]
        calls.append((argv, kw))
        if argv[:2] == ["docker", "info"]:
            up = state.docker_up or state.colima_started
            return SimpleNamespace(returncode=0 if up else 1, stdout="", stderr="")
        if argv[0] == "colima":
            state.colima_started = True
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if argv[0] == "launchctl" and len(argv) > 1 and argv[1] == "print":
            return SimpleNamespace(
                returncode=0 if state.loaded else 113, stdout="", stderr=""
            )
        if argv[0] == "launchctl" and "list" in argv:
            out = f"{srv.LAUNCHD_LABEL}\n" if state.loaded else "other.agent\n"
            return SimpleNamespace(returncode=0, stdout=out, stderr="")
        if "up" in argv:
            return SimpleNamespace(returncode=state.up_rc, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(srv.subprocess, "run", fake_run)
    # Colima is present for the fallback tests; individual tests override.
    monkeypatch.setattr(
        srv, "which", lambda name: "/opt/homebrew/bin/colima" if name == "colima" else None
    )
    return SimpleNamespace(
        plist=plist, calls=calls, state=state, module=srv, unseals=unseals
    )


class TestServeStart:
    def test_start_writes_run_at_load_plist(self, serve_world):
        from cove.serve import serve

        result = CliRunner().invoke(serve, ["start"])
        assert result.exit_code == 0, result.output
        data = plistlib.loads(serve_world.plist.read_bytes())
        assert data["Label"] == "app.cove.serve"
        assert data["RunAtLoad"] is True
        assert data["ProgramArguments"][-2:] == ["serve", "run"], data["ProgramArguments"]
        assert data["StandardOutPath"] == str(serve_world.module.LOG_PATH)
        assert data["StandardErrorPath"] == str(serve_world.module.LOG_PATH)

    def test_start_sets_no_calendar_or_keepalive(self, serve_world):
        """Login-time one-shot, not a daemon and not a schedule: neither a
        StartCalendarInterval (that is `cove update auto`) nor KeepAlive."""
        from cove.serve import serve

        CliRunner().invoke(serve, ["start"])
        data = plistlib.loads(serve_world.plist.read_bytes())
        assert "StartCalendarInterval" not in data
        assert "KeepAlive" not in data

    def test_start_plist_path_names_the_cove_bin_dir(
        self, serve_world, tmp_path, monkeypatch
    ):
        """Same 2026-10-27 defect as the update agent: launchd's default PATH
        omits the user bin dir, so `serve run`'s `cove up` re-exec could not
        resolve `cove`. The rendered PATH must name the resolved binary."""
        from cove.serve import serve

        bin_dir = tmp_path / "userbin"
        bin_dir.mkdir()
        cove_bin = bin_dir / "cove"
        cove_bin.write_text("#!/bin/sh\nexit 0\n")
        cove_bin.chmod(0o755)
        monkeypatch.setattr(serve_world.module, "_cove_bin", lambda: str(cove_bin))

        result = CliRunner().invoke(serve, ["start"])
        assert result.exit_code == 0, result.output
        data = plistlib.loads(serve_world.plist.read_bytes())
        assert data["ProgramArguments"][0] == str(cove_bin)

        agent_path = data["EnvironmentVariables"]["PATH"]
        assert str(bin_dir) in agent_path.split(os.pathsep)
        assert shutil.which("cove", path=agent_path) == str(cove_bin)

    def test_start_bootstraps_into_user_session(self, serve_world):
        from cove.serve import serve

        result = CliRunner().invoke(serve, ["start"])
        assert result.exit_code == 0, result.output
        bootstraps = [c for (c, _) in serve_world.calls if c[:2] == ["launchctl", "bootstrap"]]
        assert len(bootstraps) == 1, serve_world.calls
        assert bootstraps[0][2].startswith("gui/"), bootstraps[0]
        assert bootstraps[0][3] == str(serve_world.plist), bootstraps[0]

    def test_start_is_idempotent_bootout_then_bootstrap(self, serve_world):
        """Re-register must bootout first so a second `start` replaces the
        loaded agent rather than failing on a duplicate label."""
        from cove.serve import serve

        CliRunner().invoke(serve, ["start"])
        seq = [c[1] for (c, _) in serve_world.calls if c[0] == "launchctl"]
        assert "bootout" in seq and "bootstrap" in seq, seq
        assert seq.index("bootout") < seq.index("bootstrap"), seq

    def test_start_unloads_the_loaded_label_before_bootstrap(
        self, tmp_path, monkeypatch
    ):
        """The mock above models argv order; this one models launchctl's real
        rule: bootstrap on a loaded label exits 5, and only the service-target
        bootout form (`gui/<uid>/<label>`) actually unloads (2026-10-27)."""
        import cove.serve as srv
        from launchd_fake import FakeLaunchd

        plist = tmp_path / "LaunchAgents" / "app.cove.serve.plist"
        monkeypatch.setattr(srv, "PLIST_PATH", plist)
        monkeypatch.setattr(srv, "_cove_bin", lambda: "/fake/bin/cove")
        fake = FakeLaunchd()
        fake.loaded.add("app.cove.serve")
        monkeypatch.setattr(srv.subprocess, "run", fake)

        result = CliRunner().invoke(srv.serve, ["start"])

        assert result.exit_code == 0, result.output
        assert [
            "launchctl",
            "bootout",
            f"gui/{os.getuid()}/app.cove.serve",
        ] in fake.calls, fake.calls
        assert "app.cove.serve" in fake.loaded


class TestServeStop:
    def test_stop_boots_out_and_removes_plist(self, serve_world):
        from cove.serve import serve

        serve_world.plist.parent.mkdir(parents=True, exist_ok=True)
        serve_world.plist.write_text("<plist/>")
        result = CliRunner().invoke(serve, ["stop"])
        assert result.exit_code == 0, result.output
        assert not serve_world.plist.exists()
        assert any(c[:2] == ["launchctl", "bootout"] for (c, _) in serve_world.calls)

    def test_stop_unloads_a_loaded_label_when_the_plist_is_gone(
        self, tmp_path, monkeypatch
    ):
        """The reported mismatch: `stop` said "not installed" while launchd had
        the label loaded, because it trusted the plist file instead of asking
        launchd. It must bootout the loaded agent either way."""
        import cove.serve as srv
        from launchd_fake import FakeLaunchd

        plist = tmp_path / "LaunchAgents" / "app.cove.serve.plist"
        monkeypatch.setattr(srv, "PLIST_PATH", plist)
        fake = FakeLaunchd()
        fake.loaded.add("app.cove.serve")
        monkeypatch.setattr(srv.subprocess, "run", fake)

        result = CliRunner().invoke(srv.serve, ["stop"])

        assert result.exit_code == 0, result.output
        assert "app.cove.serve" not in fake.loaded, "stop must unload a loaded agent"
        assert "nothing to do" not in result.output
        assert "unloaded" in result.output, result.output

    def test_stop_off_alias_removes_plist(self, serve_world):
        from cove.serve import serve

        serve_world.plist.parent.mkdir(parents=True, exist_ok=True)
        serve_world.plist.write_text("<plist/>")
        result = CliRunner().invoke(serve, ["stop", "--off"])
        assert result.exit_code == 0, result.output
        assert not serve_world.plist.exists()

    def test_stop_when_absent_is_noop(self, serve_world):
        from cove.serve import serve

        result = CliRunner().invoke(serve, ["stop"])
        assert result.exit_code == 0, result.output
        assert "nothing to do" in result.output


class TestServeStatus:
    def test_status_reports_installed_and_loaded(self, serve_world):
        from cove.serve import serve

        serve_world.plist.parent.mkdir(parents=True, exist_ok=True)
        serve_world.plist.write_text("<plist/>")
        serve_world.state.loaded = True
        result = CliRunner().invoke(serve, ["status"])
        assert result.exit_code == 0, result.output
        assert "installed" in result.output
        assert "loaded" in result.output

    def test_status_reports_absent(self, serve_world):
        from cove.serve import serve

        result = CliRunner().invoke(serve, ["status"])
        assert result.exit_code == 0, result.output
        assert "absent" in result.output
        assert "not loaded" in result.output


class TestServeRun:
    def test_probes_docker_and_skips_colima_when_daemon_up(self, serve_world):
        from cove.serve import serve

        serve_world.state.docker_up = True
        result = CliRunner().invoke(serve, ["run"])
        assert result.exit_code == 0, result.output
        assert any(c[:2] == ["docker", "info"] for (c, _) in serve_world.calls)
        assert not any(c[0] == "colima" for (c, _) in serve_world.calls), (
            "a healthy daemon must never trigger a colima start"
        )

    def test_falls_back_to_colima_when_no_daemon(self, serve_world):
        from cove.serve import serve

        serve_world.state.docker_up = False  # only colima start brings it up
        result = CliRunner().invoke(serve, ["run"])
        assert result.exit_code == 0, result.output
        colima = [c for (c, _) in serve_world.calls if c[0] == "colima"]
        assert colima == [["colima", "start"]], serve_world.calls

    def test_no_colima_and_no_daemon_fails_loud(self, serve_world, monkeypatch):
        from cove.serve import serve

        serve_world.state.docker_up = False
        monkeypatch.setattr(serve_world.module, "which", lambda name: None)
        result = CliRunner().invoke(serve, ["run"])
        assert result.exit_code != 0
        assert "No Docker daemon answered" in result.output
        assert not any("up" in c for (c, _) in serve_world.calls), (
            "converge must not run without a runtime"
        )

    def test_converges_with_no_provision_then_unseals(self, serve_world):
        from cove.serve import serve

        result = CliRunner().invoke(serve, ["run"])
        assert result.exit_code == 0, result.output
        ups = [c for (c, _) in serve_world.calls if "up" in c]
        assert ups, serve_world.calls
        assert ups[0][-2:] == ["--no-provision", "--non-interactive"], ups[0]
        assert serve_world.unseals == [True], (
            "the payload must unseal after converging"
        )

    def test_up_failure_warns_and_exits_nonzero(self, serve_world):
        from cove.serve import serve

        serve_world.state.up_rc = 1
        result = CliRunner().invoke(serve, ["run"])
        assert result.exit_code == 1
        assert "the stack may be" in result.output
        assert "cove status" in result.output

    def test_unseal_failure_warns_and_exits_nonzero(self, serve_world, monkeypatch):
        """The real `unseal_or_warn` runs here: a locked keychain (RuntimeError
        from the keystore read) must not raise, must name `cove vault unseal`,
        and must mark the agent run as failed — after the converge already ran.
        """
        from cove.serve import serve
        import cove.vault as vlt

        def _boom():
            raise RuntimeError("Keystore read failed for cove/vault/unseal-1")

        monkeypatch.setattr(vlt, "ensure_unsealed", _boom)
        result = CliRunner().invoke(serve, ["run"])
        assert result.exit_code == 1, result.output
        assert "could not be unsealed automatically" in result.output
        assert "cove vault unseal" in result.output
        assert any("up" in c for (c, _) in serve_world.calls), (
            "the converge must have run before the unseal attempt"
        )
