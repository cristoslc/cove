"""Credential provenance: the ambient environment must not beat the files of record.

2026-10-27 defect: `cove-litellm` and `cove-bifrost` carried a
`SYNTHETIC_API_KEY` whose fingerprint did not match `<COVE_DATA_ROOT>/litellm/
local.env`, the service's declared `env_file`. `docker compose` interpolates the
invoking shell ahead of the compose `.env`, so an exported credential silently
wins over the file of record: a value nobody manages goes live, the next clean
shell silently switches it, and the ambient value enters every affected
service's config hash (a churn vector in the same family as #105's dir
alternation).

These tests are hermetic: they drive `cove.credential_env` directly and the
compose/Ansible subprocess boundaries with fakes. No Docker, no live stack.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import yaml

import cove.cli
from cove import credential_env as ce


def _project_root() -> Path:
    start = Path(__file__).resolve().parent
    for _ in range(6):
        if (start / "compose" / "inventory.yml").exists():
            return start
        start = start.parent
    raise RuntimeError(f"Cannot find project root from {__file__}")


PROJECT_ROOT = _project_root()
COMPOSE_DIR = PROJECT_ROOT / "compose"
BRINGUP = COMPOSE_DIR / "bringup.yml"


def _fp(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:12]


@pytest.fixture(autouse=True)
def _reset_warnings():
    ce.reset_warning_state()
    yield
    ce.reset_warning_state()


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """A compose dir plus a data root, with every credential cleared from env."""
    compose_dir = tmp_path / "compose"
    compose_dir.mkdir()
    (compose_dir / "inventory.yml").write_text("all:\n  hosts: {}\n")
    data_root = tmp_path / "data"
    data_root.mkdir()
    monkeypatch.setenv("COVE_DATA_ROOT", str(data_root))
    monkeypatch.delenv(ce.ALLOW_AMBIENT_ENV, raising=False)
    for name in ce.CREDENTIAL_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    return compose_dir, data_root


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


# --------------------------------------------------------------------------
# The scrubbed-name list is complete and single-sourced
# --------------------------------------------------------------------------

#: Credential variables the compose files interpolate with ${NAME}.
INTERPOLATED_CREDENTIALS = {
    "OLLAMA_API_KEY",
    "LITELLM_MASTER_KEY",
    "LITELLM_DB_PASSWORD",
    "LITELLM_UI_USERNAME",
    "LITELLM_UI_PASSWORD",
    "BIFROST_ENCRYPTION_KEY",
    "BIFROST_ADMIN_USERNAME",
    "BIFROST_ADMIN_PASSWORD",
    "SPEEDTEST_APP_KEY",
    "SPEEDTEST_ADMIN_EMAIL",
    "SPEEDTEST_ADMIN_PASSWORD",
    "ZROK_ACCOUNT_TOKEN",
}


def _interpolated_names() -> set[str]:
    names: set[str] = set()
    for path in COMPOSE_DIR.glob("*.yml"):
        for match in re.finditer(r"\$\{([A-Z0-9_]+)", path.read_text()):
            names.add(match.group(1))
    return names


class TestCredentialNameSurface:
    def test_every_interpolated_credential_is_scrubbed(self):
        missing = INTERPOLATED_CREDENTIALS - set(ce.CREDENTIAL_ENV_NAMES)
        assert not missing, (
            "every credential the compose set interpolates must be scrubbed; "
            f"missing: {sorted(missing)}"
        )
        assert INTERPOLATED_CREDENTIALS <= _interpolated_names(), (
            "the expected set drifted from compose/docker-compose.yml"
        )

    def test_env_file_only_credentials_are_listed(self):
        names = set(ce.CREDENTIAL_ENV_NAMES)
        assert "SYNTHETIC_API_KEY" in names, (
            "the Synthetic provider key (env_file-only) is the defect's subject"
        )
        assert "BIFROST_CLIENT_VIRTUAL_KEY" in names

    def test_bringup_unset_list_equals_the_python_list(self):
        data = yaml.safe_load(BRINGUP.read_text())
        play = data[0] if isinstance(data, list) else data
        declared = tuple(play["vars"]["credential_env_names"])
        assert declared == ce.CREDENTIAL_ENV_NAMES, (
            "compose/bringup.yml credential_env_names must match "
            "cove.credential_env.CREDENTIAL_ENV_NAMES (single source of truth)"
        )

    def test_bringup_warns_and_unsets_before_compose(self):
        data = yaml.safe_load(BRINGUP.read_text())
        play = data[0] if isinstance(data, list) else data
        tasks = play["tasks"]
        compose_task = next(
            t for t in tasks if t.get("name") == "Bring up pod via docker compose"
        )
        shell = compose_task["ansible.builtin.shell"]
        assert "unset {{ credential_env_names | join(' ') }}" in shell, (
            "a direct ansible-playbook run must strip ambient credentials too"
        )
        assert "COVE_ALLOW_AMBIENT_CREDENTIALS" in shell, (
            "the explicit override must survive the direct-playbook path"
        )
        warn_task = next(
            t for t in tasks
            if t.get("name") == "Warn when ambient credentials would override the files of record"
        )
        assert warn_task["loop"] == "{{ credential_env_names }}"
        assert "lookup('env', item)" in warn_task["when"]


# --------------------------------------------------------------------------
# Scrub semantics
# --------------------------------------------------------------------------

class TestScrubbedEnvironment:
    def test_removes_ambient_credentials_and_starts_from_os_environ(
        self, sandbox, monkeypatch
    ):
        compose_dir, _ = sandbox
        _write(compose_dir / ".env", "OLLAMA_API_KEY=file-ollama\n")
        monkeypatch.setenv("OLLAMA_API_KEY", "file-ollama")
        monkeypatch.setenv("SAFE_VALUE", "kept")
        env = ce.scrubbed_environment(compose_dir)
        assert "OLLAMA_API_KEY" not in env
        assert env["SAFE_VALUE"] == "kept"
        assert env["COVE_DATA_ROOT"], "COVE_DATA_ROOT is a path, never scrubbed"

    def test_matching_ambient_value_is_silent(self, sandbox, monkeypatch, capsys):
        compose_dir, _ = sandbox
        _write(compose_dir / ".env", "LITELLM_MASTER_KEY=sk-file\n")
        monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-file")
        ce.scrubbed_environment(compose_dir)
        captured = capsys.readouterr()
        assert "WARNING" not in captured.err

    def test_divergent_ambient_warns_names_both_fingerprints_and_no_values(
        self, sandbox, monkeypatch, capsys
    ):
        compose_dir, _ = sandbox
        _write(compose_dir / ".env", "LITELLM_MASTER_KEY=sk-file-value\n")
        monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-ambient-value")
        env = ce.scrubbed_environment(compose_dir)
        err = capsys.readouterr().err
        assert "LITELLM_MASTER_KEY" in err
        assert _fp("sk-ambient-value") in err
        assert _fp("sk-file-value") in err
        assert "sk-ambient-value" not in err, "values must never be printed"
        assert "sk-file-value" not in err, "values must never be printed"
        assert "compose .env" in err
        assert ce.ALLOW_AMBIENT_ENV in err
        assert "LITELLM_MASTER_KEY" not in env

    def test_divergent_bifrost_variable_is_pinned_too(
        self, sandbox, monkeypatch, capsys
    ):
        compose_dir, _ = sandbox
        _write(compose_dir / ".env", "BIFROST_ADMIN_PASSWORD=file-pass\n")
        monkeypatch.setenv("BIFROST_ADMIN_PASSWORD", "ambient-pass")
        env = ce.scrubbed_environment(compose_dir)
        err = capsys.readouterr().err
        assert "BIFROST_ADMIN_PASSWORD" in err
        assert _fp("ambient-pass") in err and _fp("file-pass") in err
        assert "BIFROST_ADMIN_PASSWORD" not in env

    def test_env_file_value_is_the_resolution_for_env_file_only_credentials(
        self, sandbox, monkeypatch, capsys
    ):
        compose_dir, data_root = sandbox
        _write(data_root / "litellm" / "local.env", "SYNTHETIC_API_KEY=file-syn\n")
        monkeypatch.setenv("SYNTHETIC_API_KEY", "ambient-syn")
        ce.scrubbed_environment(compose_dir)
        err = capsys.readouterr().err
        assert "SYNTHETIC_API_KEY" in err
        assert "litellm/local.env" in err
        assert _fp("ambient-syn") in err and _fp("file-syn") in err

    def test_ambient_with_no_file_value_warns_that_it_resolves_to_unset(
        self, sandbox, monkeypatch, capsys
    ):
        compose_dir, _ = sandbox
        monkeypatch.setenv("ZROK_ACCOUNT_TOKEN", "ambient-only")
        ce.scrubbed_environment(compose_dir)
        err = capsys.readouterr().err
        assert "ZROK_ACCOUNT_TOKEN" in err
        assert "resolves to unset" in err

    def test_explicit_opt_in_keeps_the_ambient_environment(
        self, sandbox, monkeypatch, capsys
    ):
        compose_dir, _ = sandbox
        _write(compose_dir / ".env", "LITELLM_MASTER_KEY=sk-file\n")
        monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-ambient")
        monkeypatch.setenv(ce.ALLOW_AMBIENT_ENV, "1")
        env = ce.scrubbed_environment(compose_dir)
        assert env["LITELLM_MASTER_KEY"] == "sk-ambient"
        assert ce.ALLOW_AMBIENT_ENV in capsys.readouterr().err

    def test_files_of_record_are_never_rewritten(self, sandbox, monkeypatch):
        compose_dir, data_root = sandbox
        env_path = _write(compose_dir / ".env", "OLLAMA_API_KEY=file\n")
        local = _write(data_root / "litellm" / "local.env", "SYNTHETIC_API_KEY=file2\n")
        monkeypatch.setenv("OLLAMA_API_KEY", "ambient")
        monkeypatch.setenv("SYNTHETIC_API_KEY", "ambient2")
        ce.scrubbed_environment(compose_dir)
        assert env_path.read_text() == "OLLAMA_API_KEY=file\n"
        assert local.read_text() == "SYNTHETIC_API_KEY=file2\n"


class TestConvergeChurnContract:
    def test_two_differently_equipped_shells_produce_the_same_child_env(
        self, sandbox, monkeypatch
    ):
        """Same files, different ambient credentials -> identical compose inputs."""
        compose_dir, data_root = sandbox
        _write(
            compose_dir / ".env",
            "OLLAMA_API_KEY=file-ollama\n"
            "LITELLM_MASTER_KEY=sk-file\n"
            "BIFROST_ADMIN_PASSWORD=file-pass\n",
        )
        _write(data_root / "litellm" / "local.env", "SYNTHETIC_API_KEY=file-syn\n")

        monkeypatch.setenv("OLLAMA_API_KEY", "shell-a-ollama")
        monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-shell-a")
        monkeypatch.setenv("SYNTHETIC_API_KEY", "shell-a-syn")
        first = ce.scrubbed_environment(compose_dir)

        ce.reset_warning_state()
        monkeypatch.setenv("OLLAMA_API_KEY", "shell-b-ollama")
        monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-shell-b")
        monkeypatch.setenv("SYNTHETIC_API_KEY", "shell-b-syn")
        second = ce.scrubbed_environment(compose_dir)

        assert first == second, (
            "a converge from a differently-equipped shell must not change the "
            "compose config hash for unchanged services"
        )
        for name in ce.CREDENTIAL_ENV_NAMES:
            assert name not in first


# --------------------------------------------------------------------------
# Provisioning: ambient credentials are not custody without the opt-in
# --------------------------------------------------------------------------

class TestProvisioningGate:
    def test_litellm_master_key_ambient_ignored_without_opt_in(
        self, sandbox, monkeypatch, capsys
    ):
        import cove.litellm as ll
        compose_dir, _ = sandbox
        env_path = _write(compose_dir / ".env", "LITELLM_MASTER_KEY=sk-file\n")
        monkeypatch.setattr(ll, "_compose_env_path", lambda: env_path)
        monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-ambient")
        assert ce.credential_from_ambient(
            "LITELLM_MASTER_KEY", compose_dir
        ) is None
        assert "WARNING" in capsys.readouterr().err
        assert env_path.read_text() == "LITELLM_MASTER_KEY=sk-file\n"

    def test_litellm_master_key_ambient_honored_with_opt_in(
        self, sandbox, monkeypatch
    ):
        compose_dir, _ = sandbox
        monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-ambient")
        monkeypatch.setenv(ce.ALLOW_AMBIENT_ENV, "yes")
        assert ce.credential_from_ambient(
            "LITELLM_MASTER_KEY", compose_dir
        ) == "sk-ambient"

    def test_bifrost_provisioning_ignores_ambient_password(
        self, sandbox, monkeypatch, capsys
    ):
        from cove import bifrost as bf
        compose_dir, _ = sandbox
        env_path = _write(compose_dir / ".env", "BIFROST_ADMIN_PASSWORD=file-pass\n")
        monkeypatch.setattr(bf, "_compose_env_path", lambda: env_path)
        monkeypatch.setenv("BIFROST_ADMIN_PASSWORD", "ambient-pass")
        value = bf._ensure_secret(
            "BIFROST_ADMIN_PASSWORD", "op://Private/Bifrost Gateway/admin_password",
            lambda: "generated-pass",
        )
        assert value == "file-pass", "the file of record wins"
        assert "ambient-pass" not in env_path.read_text()
        err = capsys.readouterr().err
        assert "BIFROST_ADMIN_PASSWORD" in err
        assert _fp("ambient-pass") in err and _fp("file-pass") in err
        assert "ambient-pass" not in err

    def test_bifrost_synthetic_key_projects_the_file_value_and_warns(
        self, sandbox, monkeypatch, capsys
    ):
        from cove import bifrost as bf
        compose_dir, data_root = sandbox
        litellm_env = _write(
            data_root / "litellm" / "local.env", "SYNTHETIC_API_KEY=file-syn\n"
        )
        monkeypatch.setattr(bf, "_compose_env_path", lambda: compose_dir / ".env")
        monkeypatch.setenv("SYNTHETIC_API_KEY", "ambient-syn")
        bf._ensure_synthetic_key()
        bifrost_env = data_root / "bifrost" / "local.env"
        assert "SYNTHETIC_API_KEY=file-syn" in bifrost_env.read_text()
        assert "ambient-syn" not in bifrost_env.read_text()
        assert litellm_env.read_text() == "SYNTHETIC_API_KEY=file-syn\n"
        err = capsys.readouterr().err
        assert "SYNTHETIC_API_KEY" in err and _fp("ambient-syn") in err


# --------------------------------------------------------------------------
# Subprocess boundaries: compose and Ansible get the scrubbed child env
# --------------------------------------------------------------------------

class TestComposeSubprocessBoundary:
    def test_litellm_up_hands_compose_a_scrubbed_env(self, sandbox, monkeypatch):
        from click.testing import CliRunner
        import cove.litellm as ll

        compose_dir, _ = sandbox
        _write(compose_dir / ".env", "LITELLM_MASTER_KEY=sk-file\n")
        monkeypatch.setenv("COVE_COMPOSE_DIR", str(compose_dir))
        monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-ambient")
        monkeypatch.setenv("SYNTHETIC_API_KEY", "ambient-syn")
        monkeypatch.setattr(ll, "_ensure_master_key", lambda: "sk-file")
        monkeypatch.setattr(ll, "_prepare_runtime_files", lambda: None)
        monkeypatch.setattr(ll, "ensure_compose_source_ready", lambda d: None)

        calls = []

        def _fake_run(*args, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(returncode=0)

        monkeypatch.setattr(ll.subprocess, "run", _fake_run)
        result = CliRunner().invoke(ll.up)
        assert result.exit_code == 0, result.output
        env = calls[-1]["env"]
        for name in ce.CREDENTIAL_ENV_NAMES:
            assert name not in env, f"{name} reached docker compose unchanged"
        assert env["COVE_DATA_ROOT"] == str(sandbox[1])

    def test_cove_up_hands_ansible_a_scrubbed_env(self, tmp_path, monkeypatch):
        """The bringup playbook reads env, so the Popen env must be scrubbed."""
        home = tmp_path / "home"
        home.mkdir()
        compose_dir = tmp_path / "compose"
        compose_dir.mkdir()
        (compose_dir / "inventory.yml").write_text("all:\n  hosts: {}\n")
        data_root = tmp_path / "data"
        data_root.mkdir()
        (compose_dir / ".env").write_text(
            f"COVE_DATA_ROOT={data_root}\nFORGEJO_DATA_ROOT={data_root}\n"
            "LITELLM_MASTER_KEY=sk-file\n"
        )
        host_vars = tmp_path / "host.yml"
        host_vars.write_text("admin_username: x\n")

        # The edge-auth step reads the llmproxy seed and may provision the
        # client-token item; this test targets env scrubbing, so stub the seam.
        edge_vars = tmp_path / "edge-vars.yml"
        edge_vars.write_text("llmproxy_client_key: x\nllmproxy_upstream_key: y\n")
        monkeypatch.setattr("cove.cli.edge_secret_vars_file", lambda: edge_vars)

        monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: tmp_path))
        monkeypatch.setenv("COVE_DATA_ROOT", str(data_root))
        monkeypatch.delenv("COVE_COMPOSE_DIR", raising=False)
        monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-ambient")
        monkeypatch.setenv("BIFROST_ADMIN_PASSWORD", "ambient-pass")

        monkeypatch.setattr(cove.cli, "maybe_reextract", lambda: False)
        monkeypatch.setattr(cove.cli, "ensure_init", lambda: compose_dir)
        monkeypatch.setattr(cove.cli, "bundle_is_current", lambda: True)
        monkeypatch.setattr(cove.cli, "ensure_host_vars", lambda: host_vars)
        monkeypatch.setattr(cove.cli, "passwordless_sudo_ok", lambda: True)
        monkeypatch.setattr(cove.cli, "_detect_running_optional_profiles", lambda: [])
        monkeypatch.setattr(cove.cli, "_vault_runtime_state", lambda: {})
        monkeypatch.setattr(cove.cli, "_vault_restarted_since", lambda before: False)
        monkeypatch.setattr(
            "cove.status.check_all",
            lambda: [SimpleNamespace(ok=True, optional=False)],
        )
        monkeypatch.setattr("cove.status.print_status", lambda results: None)

        captured = {}

        class _Proc:
            returncode = 0
            stdout = iter([])

            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def wait(self, timeout=None):
                return 0

            def communicate(self, input=None, timeout=None):
                return (b"", b"")

            def poll(self):
                return 0

            def kill(self):
                pass

        def _popen(cmd, **kwargs):
            captured.setdefault("envs", []).append(kwargs.get("env"))
            p = _Proc()
            p.args = cmd
            return p

        monkeypatch.setattr(cove.cli.subprocess, "Popen", _popen)

        cove.cli.up.callback(
            no_provision=True, no_upgrade=True, all_=False, log=False
        )
        assert captured["envs"], "ansible-playbook was never spawned"
        env = captured["envs"][0]
        assert env is not None
        for name in ce.CREDENTIAL_ENV_NAMES:
            assert name not in env, f"{name} reached ansible-playbook unchanged"
        assert env["COVE_DATA_ROOT"] == str(data_root)
