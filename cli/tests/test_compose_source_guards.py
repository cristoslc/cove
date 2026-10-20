"""Guards against compose sources that collapse bind mounts or hijack the live project.

Incident 20261018-015539: a bb git worktree ran `cove up` with compose project
name `cove` from a compose dir whose `.env` was partial (SPEEDTEST_* keys only,
no COVE_DATA_ROOT / FORGEJO_DATA_ROOT). `${COVE_DATA_ROOT}/x` interpolated to
container-absolute `/x`, and seven live containers were recreated with the wrong
(VM-internal) bind targets. The worktree's partial `.env` came from
`cove speedtest up` writing a key via `_upsert_env` into a dir that had no
rendered `.env`; `bringup.yml` then skipped its "first boot only" render because
a `.env` existed, so the incomplete file was left in place.

Two independent hazards, two guards:

  Guard 1 — an unusable data root. A compose dir whose `.env` exists but whose
  effective COVE_DATA_ROOT / FORGEJO_DATA_ROOT is unset/empty must abort loudly,
  naming the resolved compose dir and every missing key, instead of handing
  Docker an empty interpolation. The canonical install dir is exempt: `cove up`
  legitimately starts there with no `.env` yet (bringup renders it first).

  Guard 2 — the hijack. `docker-compose.yml` pins `name: cove`; compose keys a
  project by (name, working directory), so another compose dir that declares
  the live name and a *different* data root would recreate the live containers
  against foreign storage. Such a dir is refused unless the operator sets an
  explicit override, or its effective data root is the canonical one (a
  same-data recreation is harmless, which is why the dev checkout still works).

These tests are hermetic: they drive the guard helpers directly and the
`cove up` / `cove down` callbacks with `Path.cwd` and `Path.home` patched, so
no real Docker, `.env`, or live stack is touched.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import click
import pytest

import cove.cli
from cove.stateless import (
    NONCANONICAL_OVERRIDE_ENV,
    declared_compose_project_name,
    effective_data_root,
    ensure_compose_source_ready,
    require_live_project_from_canonical_dir,
    require_usable_data_root,
)

# A compose .env carrying every required data root the stack interpolates.
WELL_FORMED_ENV = (
    "COVE_DATA_ROOT=/srv/cove-data\n"
    "FORGEJO_DATA_ROOT=/srv/cove-data\n"
)


@pytest.fixture
def monkeypatch_home(tmp_path, monkeypatch):
    """Point Path.home() at an isolated dir so canonical paths are deterministic."""
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


@pytest.fixture
def isolated_compose_resources(tmp_path, monkeypatch, monkeypatch_home):
    """Keep the `cove up` callback away from the operator's installed resources.

    Mirrors test_cli.py's fixture: Path.home points into tmp_path, and the two
    resource entry points the up callback calls before the guard are stubbed.
    """
    compose_dir = monkeypatch_home / ".config" / "cove" / "compose"
    compose_dir.mkdir(parents=True)
    monkeypatch.setattr(cove.cli, "ensure_init", lambda: compose_dir)
    monkeypatch.setattr(cove.cli, "maybe_reextract", lambda: False)
    return compose_dir


@pytest.fixture
def _fake_ansible_popen(monkeypatch):
    """Fake the Popen `_run_ansible` tees through, so no real ansible runs."""

    class _Proc:
        def __init__(self, returncode=0, out=()):
            self.stdout = iter(out)
            self.returncode = returncode

        def wait(self):
            return self.returncode

    holder: dict[str, list] = {"calls": []}

    def _popen_factory(*args, **kwargs):
        holder["calls"].append(args[0])
        return _Proc()

    monkeypatch.setattr("cove.cli.subprocess.Popen", _popen_factory)
    monkeypatch.setattr("cove.cli.passwordless_sudo_ok", lambda: False)
    return holder


def _invoke_callback(command: str, **kwargs) -> object:
    callback = getattr(cove.cli, command).callback
    assert callback is not None, f"command {command!r} has no callback"
    return callback(**kwargs)


def _project_root_for_this_file() -> Path:
    start = Path(__file__).resolve().parent
    for _ in range(6):
        if (start / "compose" / "inventory.yml").exists():
            return start
        start = start.parent
    raise RuntimeError(f"Cannot find project root from {__file__}")


def _write_compose_dir(
    root: Path,
    *,
    env: str | None,
    project_name: str | None,
    inventory: bool = True,
) -> Path:
    """Materialize a minimal compose dir: inventory.yml (+ .env / name:).

    `env` is the raw `.env` content, or None for no `.env` at all.
    """
    compose_dir = root / "compose"
    compose_dir.mkdir(parents=True, exist_ok=True)
    if inventory:
        (compose_dir / "inventory.yml").write_text("---\n")
    if env is not None:
        (compose_dir / ".env").write_text(env)
    if project_name is not None:
        (compose_dir / "docker-compose.yml").write_text(f"name: {project_name}\n")
    return compose_dir


def _clear_data_root_env(monkeypatch) -> None:
    for key in ("COVE_DATA_ROOT", "FORGEJO_DATA_ROOT", NONCANONICAL_OVERRIDE_ENV):
        monkeypatch.delenv(key, raising=False)


# --------------------------------------------------------------------------
# Guard 1 — usable data root
# --------------------------------------------------------------------------

class TestEffectiveDataRoot:
    def test_env_var_wins_when_non_empty(self, tmp_path, monkeypatch):
        compose_dir = _write_compose_dir(
            tmp_path, env="COVE_DATA_ROOT=/from/env-file\n", project_name=None
        )
        monkeypatch.setenv("COVE_DATA_ROOT", "/from/process-env")
        assert effective_data_root(compose_dir) == "/from/process-env"

    def test_blank_env_var_falls_through_to_env_file(self, tmp_path, monkeypatch):
        compose_dir = _write_compose_dir(
            tmp_path, env="COVE_DATA_ROOT=/from/env-file\n", project_name=None
        )
        monkeypatch.setenv("COVE_DATA_ROOT", "")
        assert effective_data_root(compose_dir) == "/from/env-file"

    def test_env_file_value_used_when_no_process_env(self, tmp_path, monkeypatch):
        compose_dir = _write_compose_dir(
            tmp_path, env="COVE_DATA_ROOT=/from/env-file\n", project_name=None
        )
        monkeypatch.delenv("COVE_DATA_ROOT", raising=False)
        assert effective_data_root(compose_dir) == "/from/env-file"

    def test_none_when_env_file_missing_and_no_process_env(self, tmp_path, monkeypatch):
        compose_dir = _write_compose_dir(tmp_path, env=None, project_name=None)
        monkeypatch.delenv("COVE_DATA_ROOT", raising=False)
        assert effective_data_root(compose_dir) is None

    def test_none_when_env_file_has_only_other_keys(self, tmp_path, monkeypatch):
        # The incident worktree .env shape: SPEEDTEST_* only.
        compose_dir = _write_compose_dir(
            tmp_path, env="SPEEDTEST_APP_KEY=abc\n", project_name=None
        )
        monkeypatch.delenv("COVE_DATA_ROOT", raising=False)
        assert effective_data_root(compose_dir) is None

    def test_none_when_env_file_key_is_empty(self, tmp_path, monkeypatch):
        compose_dir = _write_compose_dir(tmp_path, env="COVE_DATA_ROOT=\n", project_name=None)
        monkeypatch.delenv("COVE_DATA_ROOT", raising=False)
        assert effective_data_root(compose_dir) is None


class TestRequireUsableDataRoot:
    def test_aborts_when_env_file_present_without_data_root(self, tmp_path, monkeypatch):
        compose_dir = _write_compose_dir(
            tmp_path, env="SPEEDTEST_APP_KEY=abc\n", project_name=None
        )
        _clear_data_root_env(monkeypatch)
        with pytest.raises(click.ClickException) as exc:
            require_usable_data_root(compose_dir, allow_missing_env=False)
        message = str(exc.value)
        assert "COVE_DATA_ROOT" in message
        assert "FORGEJO_DATA_ROOT" in message
        assert str(compose_dir) in message

    def test_aborts_when_data_root_is_empty_string(self, tmp_path, monkeypatch):
        compose_dir = _write_compose_dir(tmp_path, env="COVE_DATA_ROOT=\n", project_name=None)
        _clear_data_root_env(monkeypatch)
        with pytest.raises(click.ClickException):
            require_usable_data_root(compose_dir, allow_missing_env=False)

    def test_aborts_when_only_forgejo_data_root_is_missing(self, tmp_path, monkeypatch):
        # The Add.3 empty-Forgejo failure: COVE_DATA_ROOT set, FORGEJO_DATA_ROOT
        # empty, so /forgejo/git and /forgejo/gitea collapsed to VM-local paths.
        compose_dir = _write_compose_dir(
            tmp_path, env="COVE_DATA_ROOT=/srv/cove-data\n", project_name=None
        )
        _clear_data_root_env(monkeypatch)
        with pytest.raises(click.ClickException) as exc:
            require_usable_data_root(compose_dir, allow_missing_env=False)
        assert "FORGEJO_DATA_ROOT" in str(exc.value)

    def test_aborts_when_env_file_missing_and_not_allowed(self, tmp_path, monkeypatch):
        compose_dir = _write_compose_dir(tmp_path, env=None, project_name=None)
        _clear_data_root_env(monkeypatch)
        with pytest.raises(click.ClickException) as exc:
            require_usable_data_root(compose_dir, allow_missing_env=False)
        assert str(compose_dir) in str(exc.value)

    def test_allows_missing_env_file_when_flagged(self, tmp_path, monkeypatch):
        # Fresh install into the canonical dir: bringup renders a complete
        # .env before compose runs.
        compose_dir = _write_compose_dir(tmp_path, env=None, project_name=None)
        _clear_data_root_env(monkeypatch)
        require_usable_data_root(compose_dir, allow_missing_env=True)

    def test_passes_when_both_roots_present_in_env_file(self, tmp_path, monkeypatch):
        compose_dir = _write_compose_dir(
            tmp_path, env=WELL_FORMED_ENV, project_name=None
        )
        _clear_data_root_env(monkeypatch)
        require_usable_data_root(compose_dir, allow_missing_env=False)

    def test_passes_when_process_env_provides_both_roots(self, tmp_path, monkeypatch):
        compose_dir = _write_compose_dir(tmp_path, env=None, project_name=None)
        monkeypatch.setenv("COVE_DATA_ROOT", "/from/process-env")
        monkeypatch.setenv("FORGEJO_DATA_ROOT", "/from/process-env")
        require_usable_data_root(compose_dir, allow_missing_env=False)


# --------------------------------------------------------------------------
# Guard 2 — live project name from a dir with a foreign data root
# --------------------------------------------------------------------------

class TestDeclaredComposeProjectName:
    def test_reads_top_level_name(self, tmp_path):
        compose_dir = _write_compose_dir(tmp_path, env=None, project_name="cove")
        assert declared_compose_project_name(compose_dir) == "cove"

    def test_reads_non_live_name(self, tmp_path):
        compose_dir = _write_compose_dir(tmp_path, env=None, project_name="cove-staging")
        assert declared_compose_project_name(compose_dir) == "cove-staging"

    def test_none_when_no_compose_file(self, tmp_path):
        compose_dir = _write_compose_dir(tmp_path, env=None, project_name=None)
        assert declared_compose_project_name(compose_dir) is None

    def test_ignores_nested_name_keys(self, tmp_path):
        compose_dir = _write_compose_dir(tmp_path, env=None, project_name=None)
        (compose_dir / "docker-compose.yml").write_text(
            "services:\n  nginx:\n    name: cove\n"
        )
        assert declared_compose_project_name(compose_dir) is None


class TestRequireLiveProjectFromCanonicalDir:
    def test_aborts_for_live_name_with_foreign_data_root(
        self, tmp_path, monkeypatch, monkeypatch_home
    ):
        compose_dir = _write_compose_dir(
            tmp_path,
            env="COVE_DATA_ROOT=/some/other/root\nFORGEJO_DATA_ROOT=/some/other/root\n",
            project_name="cove",
        )
        _clear_data_root_env(monkeypatch)
        with pytest.raises(click.ClickException) as exc:
            require_live_project_from_canonical_dir(compose_dir)
        message = str(exc.value)
        assert str(compose_dir) in message
        assert "cove" in message
        assert NONCANONICAL_OVERRIDE_ENV in message

    def test_allows_live_name_when_data_root_is_canonical(
        self, tmp_path, monkeypatch, monkeypatch_home
    ):
        # The dev checkout shape: real .env pointing at the canonical data root
        # makes a live-name recreation harmless.
        canonical_root = monkeypatch_home / "Documents" / "cove-data"
        compose_dir = _write_compose_dir(
            tmp_path,
            env=f"COVE_DATA_ROOT={canonical_root}\nFORGEJO_DATA_ROOT={canonical_root}\n",
            project_name="cove",
        )
        _clear_data_root_env(monkeypatch)
        require_live_project_from_canonical_dir(compose_dir)

    def test_allows_live_name_from_the_canonical_dir_itself(
        self, monkeypatch, monkeypatch_home
    ):
        canonical = monkeypatch_home / ".config" / "cove" / "compose"
        canonical.mkdir(parents=True)
        (canonical / "docker-compose.yml").write_text("name: cove\n")
        _clear_data_root_env(monkeypatch)
        require_live_project_from_canonical_dir(canonical)

    def test_allows_other_project_name_anywhere(
        self, tmp_path, monkeypatch, monkeypatch_home
    ):
        compose_dir = _write_compose_dir(
            tmp_path,
            env="COVE_DATA_ROOT=/some/other/root\nFORGEJO_DATA_ROOT=/some/other/root\n",
            project_name="cove-staging",
        )
        _clear_data_root_env(monkeypatch)
        require_live_project_from_canonical_dir(compose_dir)

    def test_allows_explicit_override_env(self, tmp_path, monkeypatch, monkeypatch_home):
        compose_dir = _write_compose_dir(
            tmp_path,
            env="COVE_DATA_ROOT=/some/other/root\nFORGEJO_DATA_ROOT=/some/other/root\n",
            project_name="cove",
        )
        monkeypatch.setenv(NONCANONICAL_OVERRIDE_ENV, "1")
        require_live_project_from_canonical_dir(compose_dir)


# --------------------------------------------------------------------------
# Composite entry point + wiring through the `cove up` / `cove down` callbacks
# --------------------------------------------------------------------------

class TestEnsureComposeSourceReady:
    def test_aborts_on_partial_env_file(self, tmp_path, monkeypatch, monkeypatch_home):
        compose_dir = _write_compose_dir(
            tmp_path, env="SPEEDTEST_APP_KEY=abc\n", project_name="cove"
        )
        _clear_data_root_env(monkeypatch)
        with pytest.raises(click.ClickException) as exc:
            ensure_compose_source_ready(compose_dir)
        assert "COVE_DATA_ROOT" in str(exc.value)

    def test_allows_missing_env_in_the_canonical_dir(self, monkeypatch, monkeypatch_home):
        canonical = monkeypatch_home / ".config" / "cove" / "compose"
        canonical.mkdir(parents=True)
        (canonical / "docker-compose.yml").write_text("name: cove\n")
        _clear_data_root_env(monkeypatch)
        ensure_compose_source_ready(canonical)


class TestCoveUpGuardWiring:
    """`cove up` must abort before it hands anything to Ansible/Docker."""

    @pytest.fixture(autouse=True)
    def _isolate(self, isolated_compose_resources, monkeypatch):
        _clear_data_root_env(monkeypatch)
        monkeypatch.delenv("COVE_COMPOSE_DIR", raising=False)
        return isolated_compose_resources

    def test_up_aborts_on_partial_env_file(self, tmp_path):
        _write_compose_dir(tmp_path, env="SPEEDTEST_APP_KEY=abc\n", project_name=None)
        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path):
            with pytest.raises((click.ClickException, SystemExit)) as exc:
                _invoke_callback(
                    "up", no_provision=True, no_upgrade=True, all_=False, log=False
                )
            message = str(getattr(exc.value, "message", exc.value))
            assert "COVE_DATA_ROOT" in message

    def test_up_aborts_before_running_ansible(self, tmp_path, _fake_ansible_popen):
        _write_compose_dir(tmp_path, env="COVE_DATA_ROOT=\n", project_name=None)
        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path):
            with pytest.raises((click.ClickException, SystemExit)):
                _invoke_callback(
                    "up", no_provision=True, no_upgrade=True, all_=False, log=False
                )
        assert _fake_ansible_popen["calls"] == [], (
            "cove up must abort before invoking ansible-playbook"
        )

    def test_up_refuses_live_name_with_foreign_data_root(self, tmp_path):
        _write_compose_dir(
            tmp_path,
            env="COVE_DATA_ROOT=/some/other/root\nFORGEJO_DATA_ROOT=/some/other/root\n",
            project_name="cove",
        )
        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path):
            with pytest.raises((click.ClickException, SystemExit)) as exc:
                _invoke_callback(
                    "up", no_provision=True, no_upgrade=True, all_=False, log=False
                )
            assert "cove" in str(getattr(exc.value, "message", exc.value))


class TestCoveDownGuardWiring:
    def test_down_aborts_when_env_missing(self, tmp_path, monkeypatch):
        _write_compose_dir(tmp_path, env=None, project_name=None)
        _clear_data_root_env(monkeypatch)
        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path):
            with pytest.raises((click.ClickException, SystemExit)):
                _invoke_callback("down", volumes=False)

    def test_down_aborts_before_running_docker(self, tmp_path, monkeypatch):
        _write_compose_dir(tmp_path, env=None, project_name=None)
        _clear_data_root_env(monkeypatch)
        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path), patch(
            "subprocess.run"
        ) as mock_run:
            with pytest.raises((click.ClickException, SystemExit)):
                _invoke_callback("down", volumes=False)
        mock_run.assert_not_called()


# --------------------------------------------------------------------------
# Service commands must carry the same guard
# --------------------------------------------------------------------------

class TestServiceCommandGuards:
    """Each service `up`/`down` must refuse an unsafe compose source too.

    The incident ran the whole-stack `cove up`, but the partial `.env` that
    seeded the collapse was written by a service path (`_upsert_env`). A service
    `up` from a foreign dir is the same hazard, so every container-mutating
    service command calls the shared guard.
    """

    def test_service_modules_import_and_call_the_guard(self):
        for module_name in ("ade", "speedtest", "toolhive", "runner", "litellm", "tunnel"):
            source = (
                Path(__file__).resolve().parent.parent / "cove" / f"{module_name}.py"
            ).read_text()
            assert "ensure_compose_source_ready" in source, (
                f"cove.{module_name} must call ensure_compose_source_ready on its "
                "container-mutating commands"
            )

    def test_speedtest_up_aborts_without_data_root(self, tmp_path, monkeypatch):
        from click.testing import CliRunner
        from cove.speedtest import speedtest

        compose_dir = _write_compose_dir(
            tmp_path, env="SPEEDTEST_APP_KEY=abc\n", project_name=None
        )
        monkeypatch.setenv("COVE_COMPOSE_DIR", str(compose_dir))
        monkeypatch.delenv("COVE_DATA_ROOT", raising=False)
        monkeypatch.delenv("FORGEJO_DATA_ROOT", raising=False)

        def _boom(*a, **k):
            raise AssertionError("docker compose must not run")

        monkeypatch.setattr("cove.speedtest.subprocess.run", _boom)
        result = CliRunner().invoke(speedtest, ["up"])
        assert result.exit_code != 0
        assert "COVE_DATA_ROOT" in result.output

    def test_toolhive_up_aborts_without_data_root(self, tmp_path, monkeypatch):
        from click.testing import CliRunner
        from cove.toolhive import toolhive

        compose_dir = _write_compose_dir(tmp_path, env=None, project_name=None)
        monkeypatch.setenv("COVE_COMPOSE_DIR", str(compose_dir))
        monkeypatch.delenv("COVE_DATA_ROOT", raising=False)
        monkeypatch.delenv("FORGEJO_DATA_ROOT", raising=False)

        def _boom(*a, **k):
            raise AssertionError("docker compose must not run")

        monkeypatch.setattr("cove.toolhive.subprocess.run", _boom)
        result = CliRunner().invoke(toolhive, ["up"])
        assert result.exit_code != 0
        assert "COVE_DATA_ROOT" in result.output


# --------------------------------------------------------------------------
# Ansible pre-flight (defense in depth for a direct bringup.yml run)
# --------------------------------------------------------------------------

class TestBringupDataRootPreflight:
    """bringup.yml must mirror the Python guard before its compose invocation.

    The existing wedged-dir guards stat the *Ansible* `cove_data_root` var,
    which is always populated (`{{ ansible_env.HOME }}/Documents/cove-data`).
    They therefore never noticed the incident, where the compose `.env` value
    Compose actually interpolates was empty. This assert reads the value Compose
    would use (process env, then the rendered .env).
    """

    def _bringup_text(self) -> str:
        return (_project_root_for_this_file() / "compose" / "bringup.yml").read_text()

    def test_bringup_asserts_usable_cove_data_root(self):
        text = self._bringup_text()
        assert "Assert the compose .env carries a usable COVE_DATA_ROOT" in text, (
            "bringup.yml must assert a usable COVE_DATA_ROOT before docker compose up"
        )
        assert "regex_search('(?m)^COVE_DATA_ROOT=.+')" in text, (
            "the bringup assert must read the compose .env's COVE_DATA_ROOT line"
        )

    def test_bringup_assert_precedes_compose_invocation(self):
        text = self._bringup_text()
        guard = text.index("Assert the compose .env carries a usable COVE_DATA_ROOT")
        compose = text.index('--project-directory "{{ compose_dir }}"')
        assert guard < compose, (
            "the COVE_DATA_ROOT assert must run before the docker compose up task"
        )

    def test_bundled_bringup_matches_repo_bringup(self):
        bundled = (
            Path(__file__).resolve().parent.parent
            / "cove"
            / "resources"
            / "compose"
            / "bringup.yml"
        )
        if not bundled.is_file():
            pytest.skip("bundled resources absent — run sync_compose_resources.py")
        assert bundled.read_text() == self._bringup_text(), (
            "cli/cove/resources/compose/bringup.yml is out of sync with "
            "compose/bringup.yml — run cli/scripts/sync_compose_resources.py"
        )
