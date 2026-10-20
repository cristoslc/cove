"""Safety gate: container-touching tests must be opt-in, not filter-based.

Incident 20261018-015539: an unfiltered ``pytest`` in a Cove checkout ran
``TestE2ESpeedtestStack::test_speedtest_up_starts_container``, which invoked the
real ``cove speedtest up`` and recreated the live Compose stack from the
worktree's compose directory. A pytest *marker* is a selection mechanism, not a
safety mechanism: it only excludes a test when the invocation passes the
matching ``-m`` filter, so one omitted flag reaches the live Docker daemon.

These tests pin the opt-in gate that closes that hole:

  * a test carrying the ``live`` marker is SKIPPED (not failed) unless
    ``COVE_ALLOW_LIVE_TESTS`` is set, and the skip reason names the variable;
  * a backstop guard raises if an un-opted-in test invokes a *mutating* docker
    command, so a future container-touching test that forgot the marker is
    caught rather than reaching the daemon.

Everything here is safe to run in the default test gate: the probes are
synthetic and never touch Docker.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from live_tier_gate import (
    LIVE_MARKER,
    LIVE_OPT_IN_ENV,
    LiveContainerAccessError,
    install_container_mutation_guard,
    is_mutating_container_command,
    live_tests_allowed,
    skip_reason,
)


TESTS_DIR = Path(__file__).resolve().parent
LIVE_GATE = TESTS_DIR / "live_tier_gate.py"

# The container-touching / live-stack classes in the four e2e files. Each MUST
# carry the opt-in marker; adding a new live class without it must break
# `test_container_touching_classes_carry_live_marker` below.
LIVE_CLASSES = {
    "test_e2e_dns.py": "TestE2EDNSEndpoints",
    "test_litellm.py": "TestE2ELitellmStack",
    "test_speedtest.py": "TestE2ESpeedtestStack",
}


def _class_header(fname: str, cls: str) -> str:
    text = (TESTS_DIR / fname).read_text()
    idx = text.index(f"class {cls}")
    return "\n".join(text[:idx].rstrip().splitlines()[-4:])


class TestOptInVariable:
    def test_unset_means_not_allowed(self):
        assert live_tests_allowed({}) is False

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
    def test_truthy_values_allow(self, value):
        assert live_tests_allowed({LIVE_OPT_IN_ENV: value}) is True

    @pytest.mark.parametrize("value", ["", "0", "false", "no", "off"])
    def test_falsey_values_do_not_allow(self, value):
        assert live_tests_allowed({LIVE_OPT_IN_ENV: value}) is False

    def test_skip_reason_names_the_variable(self):
        assert LIVE_OPT_IN_ENV in skip_reason()


class TestMutationDetection:
    """Only stack-affecting docker commands are hazards. Read-only renders and
    inspection must stay allowed so the default gate keeps working (e.g.
    `docker compose config`, which never touches the daemon).

    Scope note: `docker compose exec` is NOT stack-affecting (it does not change
    which containers exist), so it is not blocked here; a test that shells to a
    container is still caught by the `live` marker when marked. A genuinely
    unmocked `exec` call is reported separately (see the PR report), not fixed
    by this gate."""

    @pytest.mark.parametrize(
        "argv,expected",
        [
            (["docker", "compose", "up", "-d"], True),
            (["docker", "compose", "--profile", "speedtest", "up", "-d"], True),
            (["docker", "compose", "--project-directory", "/x", "up", "-d"], True),
            (["docker", "compose", "down"], True),
            (["docker", "compose", "restart", "nginx"], True),
            (["docker", "run", "alpine"], True),
            (["docker-compose", "up", "-d"], True),
            (["docker", "compose", "config"], False),
            (["docker", "compose", "--project-directory", "/x", "config"], False),
            (["docker", "compose", "ps"], False),
            (["docker", "compose", "--profile", "tunnel", "exec", "-T", "tunnel", "zrok2", "list", "shares"], False),
            (["docker", "exec", "cove-litellm", "whoami"], False),
            (["docker", "inspect", "cove-litellm"], False),
            (["docker", "logs", "cove-nginx"], False),
            (["docker", "info"], False),
            (["docker", "version"], False),
            # Not docker at all — the built `cove` binary, git, bash, etc.
            (["uv", "run", "cove", "up"], False),
            (["/usr/local/bin/cove", "speedtest", "up"], False),
            (["bash", "/x/teardown.sh", "branch"], False),
            (["git", "status"], False),
            ([], False),
        ],
    )
    def test_detects_mutating_docker_only(self, argv, expected):
        assert is_mutating_container_command(argv) is expected

    def test_detects_mutating_from_shell_string(self):
        assert is_mutating_container_command("docker compose up -d") is True
        assert is_mutating_container_command("docker compose config") is False


class TestGuardBackstop:
    """The guard is the inheritance mechanism: any unmarked test that tries to
    mutate a container fails loudly instead of reaching the daemon."""

    def test_guard_blocks_mutating_docker(self, monkeypatch):
        install_container_mutation_guard(monkeypatch)
        with pytest.raises(LiveContainerAccessError):
            subprocess.run(["docker", "compose", "up", "-d"], capture_output=True)
        with pytest.raises(LiveContainerAccessError):
            subprocess.Popen(["docker", "compose", "down"])

    def test_guard_allows_readonly_docker(self, monkeypatch):
        install_container_mutation_guard(monkeypatch)
        try:
            subprocess.run(["docker", "info"], capture_output=True, timeout=10)
        except LiveContainerAccessError:  # pragma: no cover - regression guard
            pytest.fail("read-only `docker info` must not be blocked by the guard")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass  # docker absent or slow: fine, the point is the guard let it through

    def test_guard_allows_non_docker(self, monkeypatch):
        install_container_mutation_guard(monkeypatch)
        result = subprocess.run(
            [sys.executable, "-c", "print('ok')"], capture_output=True, text=True
        )
        assert result.stdout.strip() == "ok"


def _write_probe(root: Path) -> None:
    """A minimal pytest project whose only test is `live`-marked. The generated
    conftest loads the real gate by absolute path, so the probe exercises
    production behavior rather than a reimplementation. The probe writes a
    sentinel if it runs, which must never happen without the opt-in."""
    (root / "conftest.py").write_text(
        textwrap.dedent(
            f"""
            import importlib.util
            from pathlib import Path

            gate_path = Path(r"{LIVE_GATE}")
            if gate_path.exists():
                spec = importlib.util.spec_from_file_location("live_tier_gate", gate_path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                pytest_collection_modifyitems = mod.pytest_collection_modifyitems

            def pytest_configure(config):
                config.addinivalue_line("markers", "live: live test")
            """
        )
    )
    (root / "test_probe.py").write_text(
        textwrap.dedent(
            """
            from pathlib import Path

            import pytest

            @pytest.mark.live
            def test_probe():
                (Path(__file__).parent / "RAN").write_text("ran")
                assert False, "a live test must not run without the opt-in"
            """
        )
    )


def _run_probe(root: Path, **env_overrides) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != LIVE_OPT_IN_ENV}
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-rs", "-p", "no:cacheprovider", "--no-header"],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )


class TestProbeEndToEnd:
    def test_live_test_skips_without_opt_in(self, tmp_path):
        _write_probe(tmp_path)
        result = _run_probe(tmp_path)
        # The hazard this gate closes: the probe must NOT have run.
        assert not (tmp_path / "RAN").exists(), (
            "a `live` test executed without opt-in — the incident is reachable"
        )
        assert "skipped" in result.stdout, (result.stdout, result.stderr)
        assert LIVE_OPT_IN_ENV in result.stdout, (
            "the skip message must name the opt-in variable: " + result.stdout
        )

    def test_live_test_runs_with_opt_in(self, tmp_path):
        _write_probe(tmp_path)
        result = _run_probe(tmp_path, **{LIVE_OPT_IN_ENV: "1"})
        assert (tmp_path / "RAN").exists(), (
            "opt-in must let a `live` test run: " + result.stdout + result.stderr
        )


class TestRealSuiteIsGated:
    def test_container_touching_classes_carry_live_marker(self):
        for fname, cls in LIVE_CLASSES.items():
            header = _class_header(fname, cls)
            assert f"@pytest.mark.{LIVE_MARKER}" in header, (
                f"{fname}::{cls} is container-touching but is not marked "
                f"@pytest.mark.{LIVE_MARKER}; it would run under a bare pytest"
            )

    def test_local_only_e2e_class_is_not_live_marked(self):
        header = _class_header("test_e2e_stateless.py", "TestE2EStatelessInit")
        assert f"@pytest.mark.{LIVE_MARKER}" not in header, (
            "TestE2EStatelessInit only builds a wheel and runs the binary against "
            "a temp HOME; it must not be gated (no coverage is removed)"
        )
