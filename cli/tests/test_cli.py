"""Tests for CLI commands and deployment correctness."""

import yaml
from pathlib import Path
from unittest.mock import patch

import click
import pytest
from click.testing import CliRunner

from cove.project import (
    _inject, _strip, _render_agents_block, _render_context,
    _write_detail_cove, _write_project_override,
    _remove_detail_cove, _remove_project_override,
    SENTINEL_START, SENTINEL_END,
)

def _project_root() -> Path:
    start = Path(__file__).resolve().parent
    for _ in range(6):
        if (start / "compose" / "inventory.yml").exists():
            return start
        start = start.parent
    raise RuntimeError(f"Cannot find project root from {__file__}")

PROJECT_ROOT = _project_root()
COMPOSE_DIR = PROJECT_ROOT / "compose"
CLI_DIR = PROJECT_ROOT / "cli"


@pytest.fixture(autouse=True)
def _fake_ansible_popen(monkeypatch):
    """_run_ansible always tees ansible output through subprocess.Popen.
    Fake it so CLI up-flow tests never invoke the real ansible-playbook."""
    class _Proc:
        def __init__(self, args=(), returncode=0, out=()):
            self.args = args
            self.stdout = iter(out)
            self.returncode = returncode

        def wait(self):
            return self.returncode

        def poll(self):
            return self.returncode

        # subprocess.run() drives Popen as a context manager and calls
        # communicate(); support both so read-only helper subprocess calls in
        # the up flow (e.g. the Vault runtime-state snapshot) work through
        # the same fake.
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def communicate(self, input=None, timeout=None):
            return (b"", b"")
    holder: dict[str, list] = {"returncode": 0, "out": (), "calls": [], "envs": []}

    def _popen_factory(*args, **kwargs):
        holder["calls"].append(args[0])
        holder["envs"].append(kwargs.get("env"))
        return _Proc(
            args[0] if args else (),
            returncode=holder["returncode"], out=holder["out"],
        )
    monkeypatch.setattr("cove.cli.subprocess.Popen", _popen_factory)
    # Default: passwordless sudo NOT installed, so up-flow tests exercise the
    # getpass prompt path unless a test overrides this below.
    monkeypatch.setattr("cove.cli.passwordless_sudo_ok", lambda: False)
    return holder


@pytest.fixture
def isolated_compose_resources(tmp_path, monkeypatch):
    """Keep `cove up` CLI tests away from the operator's installed resources."""
    home = tmp_path / "home"
    compose_dir = home / ".config" / "cove" / "compose"
    compose_dir.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(cove.cli, "ensure_init", lambda: compose_dir)
    monkeypatch.setattr(cove.cli, "maybe_reextract", lambda: False)
    # The compose-source guard (cove.stateless.ensure_compose_source_ready)
    # refuses a compose dir whose effective data roots are empty; these
    # tests build bare tmp compose dirs, so give them a data root. Guard
    # behavior itself is covered in test_compose_source_guards.py.
    data_root = str(tmp_path / "cove-data")
    monkeypatch.setenv("COVE_DATA_ROOT", data_root)
    monkeypatch.setenv("FORGEJO_DATA_ROOT", data_root)
    return compose_dir

import cove.cli
from cove.stateless import resolve_compose_dir


def _invoke_callback(command: str, **kwargs) -> object:
    """Invoke a click command's callback, narrowing the Optional type.

    ``click.Command.callback`` is typed ``Optional[Callable]``; calling it
    directly trips the type checker ("None cannot be called"). This helper
    narrows it so call sites in the test file stay type-clean.
    """
    callback = getattr(cove.cli, command).callback
    assert callback is not None, f"command {command!r} has no callback"
    return callback(**kwargs)


@pytest.fixture(autouse=True)
def _compose_source_env(monkeypatch):
    """Model a realistic compose source for `down`/`uninstall` tests.

    The compose-source guard (cove.stateless.ensure_compose_source_ready)
    refuses a compose dir whose effective data roots are empty, and these tests
    build bare tmp compose dirs. The guard's own behavior is covered in
    test_compose_source_guards.py.
    """
    data_root = "/tmp/cove-test-data-root"
    monkeypatch.setenv("COVE_DATA_ROOT", data_root)
    monkeypatch.setenv("FORGEJO_DATA_ROOT", data_root)


class TestDeploymentManifests:
    def test_docker_compose_has_signing_env_vars(self):
        dc = COMPOSE_DIR / "docker-compose.yml"
        assert dc.exists(), f"docker-compose.yml not found at {dc}"

        with open(dc) as f:
            data = yaml.safe_load(f)

        forgejo_env = data["services"]["forgejo"]["environment"]
        env_vars = {k: v for k, v in forgejo_env.items()}

        assert "FORGEJO__repository.signing__SIGNING_KEY" in env_vars
        assert env_vars["FORGEJO__repository.signing__SIGNING_KEY"] == "default"
        assert "FORGEJO__repository.signing__SIGNING_NAME" in env_vars
        assert "Forgejo" in env_vars["FORGEJO__repository.signing__SIGNING_NAME"]
        assert "FORGEJO__repository.signing__SIGNING_EMAIL" in env_vars
        assert "forgejo@" in env_vars["FORGEJO__repository.signing__SIGNING_EMAIL"]
        assert "FORGEJO__repository.signing__INITIAL_COMMIT" in env_vars
        assert env_vars["FORGEJO__repository.signing__INITIAL_COMMIT"] == "always"
        assert "FORGEJO__repository.signing__DEFAULT_TRUST_MODEL" in env_vars
        assert env_vars["FORGEJO__repository.signing__DEFAULT_TRUST_MODEL"] == "committer"

    def test_bringup_yml_has_wait_false(self):
        bp = COMPOSE_DIR / "bringup.yml"
        assert bp.exists(), f"bringup.yml not found at {bp}"

        with open(bp) as f:
            data = yaml.safe_load(f)

        tasks = data[0]["tasks"] if isinstance(data, list) else data.get("tasks", [])
        compose_tasks = [
            t for t in tasks
            if isinstance(t, dict) and t.get("name") == "Bring up pod via docker compose"
        ]
        assert compose_tasks, "Missing 'Bring up pod via docker compose' task"
        task = compose_tasks[0]
        module_params = task.get("community.docker.docker_compose_v2", {})
        assert not module_params.get("wait"), (
            "docker_compose_v2 wait should be false to avoid sealed-Vault failures"
        )

    @staticmethod
    def _iter_tasks(tasks):
        """Yield every task dict in a bringup task list, flattening nested
        ``block``/``rescue``/``always`` entries."""
        for t in tasks:
            if not isinstance(t, dict):
                continue
            yield t
            for sub in ("block", "rescue", "always"):
                for inner in t.get(sub) or []:
                    yield from TestDeploymentManifests._iter_tasks([inner])

    def test_bringup_does_not_pin_docker_context_to_colima(self):
        """bringup must respect the operator's active Docker context on macOS
        and treat Colima only as a fallback when no daemon responds.

        Regression (2026-10-06): bringup unconditionally ran `colima start`
        and `docker context use colima` on Darwin, so every `cove up`
        pinned the engine to Colima and silently discarded an OrbStack
        (or Docker Desktop) cutover — containers landed on Colima and the
        context flip reverted ~/.docker/config.json behind the operator.
        """
        bp = COMPOSE_DIR / "bringup.yml"
        assert bp.exists(), f"bringup.yml not found at {bp}"

        with open(bp) as f:
            data = yaml.safe_load(f)
        tasks = data[0]["tasks"] if isinstance(data, list) else data.get("tasks", [])
        all_tasks = list(self._iter_tasks(tasks))

        cmd = lambda t: t.get("ansible.builtin.command") or t.get("command") or ""
        for t in all_tasks:
            assert "docker context use colima" not in cmd(t), (
                "bringup.yml must never force `docker context use colima`; "
                "the daemon check + fallback governs engine selection"
            )

        probe = [
            t for t in all_tasks
            if "docker info" in cmd(t) and t.get("when", "") in ("", None, True)
        ]
        assert probe, (
            "bringup.yml must probe `docker info` BEFORE starting Colima so the "
            "active (non-Colima) engine is detected untouched"
        )

        fallbacks = [
            t for t in all_tasks
            if "colima start" in cmd(t)
        ]
        assert fallbacks, (
            "bringup.yml must keep a Colima fallback for machines with no "
            "running Docker engine"
        )
        for t in fallbacks:
            when = t.get("when", "")
            whens = [when] if isinstance(when, str) else list(when)
            assert any("docker_probe is failed" in w for w in whens), (
                "every `colima start` must be gated on the daemon probe "
                "failing so a healthy non-Colima engine is never displaced"
            )

    def test_bringup_detects_docker_socket_gid(self):
        """Socket-mounting services must learn the daemon's in-VM socket gid
        from the engine itself, per `cove up`, instead of trusting the
        Colima-only 991 default baked into compose.

        Regression (2026-10-06): after the Colima→OrbStack cut over, the
        Forgejo runner and ToolHive stayed in a restart loop: their
        `group_add: [991]` grants matched only Colima's socket gid, while
        OrbStack's in-VM socket is root:root (gid 0) — permission denied on
        /var/run/docker.sock.
        """
        bp = COMPOSE_DIR / "bringup.yml"
        assert bp.exists(), f"bringup.yml not found at {bp}"

        content = bp.read_text()
        assert "Detect the Docker daemon socket gid" in content, (
            "bringup.yml must detect the docker socket gid from the live daemon"
        )
        assert "FORGEJO_RUNNER_DOCKER_GID" in content, (
            "bringup.yml must sync FORGEJO_RUNNER_DOCKER_GID into the .env"
        )
        assert "TOOLHIVE_DOCKER_GID" in content, (
            "bringup.yml must sync TOOLHIVE_DOCKER_GID into the .env"
        )
        assert "stat -c %g" in content, (
            "the detection must read the socket's owning group, not guess"
        )

    def test_bringup_nginx_handler_restarts_not_exec_reload(self):
        """The 'Reload nginx' handler must restart the container, not
        `docker exec … nginx -s reload`.

        Regression (2026-09-28): bringup re-renders nginx/default.conf via
        the ansible template module (atomic rename → new inode). On
        macOS/Colima, file bind-mounts pin the inode at container creation,
        so the running container's mount goes stale (link-count 0,
        open() → ENOENT) and exec'd `nginx -s reload` — which re-opens
        every config file — fails with "No such file or directory",
        killing `cove up` at the handler flush. A container restart
        re-resolves the bind by path and boots nginx on the fresh files.
        """
        bp = COMPOSE_DIR / "bringup.yml"
        assert bp.exists(), f"bringup.yml not found at {bp}"

        with open(bp) as f:
            data = yaml.safe_load(f)

        handlers = data[0]["handlers"] if isinstance(data, list) else data.get("handlers", [])
        reload_handlers = [
            h for h in handlers
            if isinstance(h, dict) and h.get("name") == "Reload nginx"
        ]
        assert reload_handlers, "Missing 'Reload nginx' handler"
        handler = reload_handlers[0]

        cmd = handler.get("ansible.builtin.command", "")
        assert "nginx -s reload" not in cmd, (
            "'Reload nginx' must not exec `nginx -s reload`: file bind-mounts "
            "pin the inode on macOS/Colima and go stale after atomic template "
            "renders (open() → ENOENT). Restart the container instead."
        )
        assert "restart" in cmd and "nginx_container_name" in cmd, (
            f"'Reload nginx' must restart the nginx container, got: {cmd!r}"
        )

    def test_bringup_guards_compose_dir_file_bind_sources(self):
        """Regression (2026-10-19 sev-2): every compose-dir FILE bind source
        must be pre-flighted for TYPE before `docker compose up`. Docker
        auto-creates a MISSING bind source as a DIRECTORY, and a file-typed
        destination then refuses to start ("mount a directory onto a file"),
        taking the whole edge down. `certs/rootCA.pem` (copied from the CA, not
        shipped in certs-less wheels) was the uncovered source; `vault/vault.hcl`
        and `forgejo-runner/config.yml` are the other compose-dir file binds.
        The guard must run before 'Bring up pod via docker compose'."""
        bp = COMPOSE_DIR / "bringup.yml"
        assert bp.exists(), f"bringup.yml not found at {bp}"

        with open(bp) as f:
            data = yaml.safe_load(f)

        tasks = data[0]["tasks"] if isinstance(data, list) else data.get("tasks", [])
        compose_up_index = next(
            i for i, t in enumerate(tasks)
            if isinstance(t, dict) and t.get("name") == "Bring up pod via docker compose"
        )

        guard_names = {
            t.get("name") for t in tasks[:compose_up_index] if isinstance(t, dict)
        }
        assert any(
            "compose-dir file bind" in (n or "").lower() for n in guard_names
        ), (
            "bringup.yml must include a guard family asserting compose-dir file "
            "bind-mount sources exist and are not directories"
        )

        text = bp.read_text()
        for source in (
            "{{ compose_dir }}/certs/rootCA.pem",
            "{{ compose_dir }}/vault/vault.hcl",
            "{{ compose_dir }}/forgejo-runner/config.yml",
        ):
            assert source in text, (
                f"compose-dir file bind guard must cover {source}"
            )

    def test_bringup_fails_loudly_on_missing_file_bind_source(self):
        """The compose-dir file bind guard must FAIL (not silently skip) when a
        source is missing or wedged as a directory: a missing file bind source
        is exactly the pre-condition that let Docker create the directory that
        blocked the nginx restart."""
        bp = COMPOSE_DIR / "bringup.yml"
        assert bp.exists(), f"bringup.yml not found at {bp}"

        with open(bp) as f:
            data = yaml.safe_load(f)

        tasks = data[0]["tasks"] if isinstance(data, list) else data.get("tasks", [])
        fail_tasks = [
            t for t in tasks
            if isinstance(t, dict)
            and "fail" in str(list(t.keys()))
            and "compose-dir file bind" in str(t.get("name", "")).lower()
        ]
        assert fail_tasks, (
            "the compose-dir file bind guard must include an ansible.builtin.fail "
            "task so a missing/directory source halts before `docker compose up`"
        )


    def test_bringup_bootstraps_compose_plugin(self):
        """The docker CLI alone lacks `docker compose`; bringup must bootstrap it.

        Regression: `cove up` failed with `unknown flag: --project-directory`
        because `docker compose` is a separate plugin that Homebrew's docker
        formula does not install. The bringup playbook must ensure the compose
        plugin is present (and discoverable) before invoking `docker compose`.
        """
        bp = COMPOSE_DIR / "bringup.yml"
        assert bp.exists(), f"bringup.yml not found at {bp}"

        with open(bp) as f:
            data = yaml.safe_load(f)

        tasks = data[0]["tasks"] if isinstance(data, list) else data.get("tasks", [])
        compose_up_index = next(
            i for i, t in enumerate(tasks)
            if isinstance(t, dict) and t.get("name") == "Bring up pod via docker compose"
        )

        bootstrap_names = {
            t.get("name") for t in tasks[:compose_up_index]
            if isinstance(t, dict)
        }

        assert any("compose" in (n or "").lower() and "plugin" in (n or "").lower() for n in bootstrap_names), (
            "bringup.yml must include a task that bootstraps the docker compose plugin "
            "before 'Bring up pod via docker compose'"
        )

    def test_nginx_binds_443_directly(self):
        """nginx must own 443 directly in compose — the pf rdr shim is gone,
        so nothing translates 443 → 8443 anymore."""
        dc = COMPOSE_DIR / "docker-compose.yml"
        assert dc.exists(), f"docker-compose.yml not found at {dc}"
        text = dc.read_text()
        assert '"0.0.0.0:443:443"' in text, (
            "nginx must publish 0.0.0.0:443:443 (no pf shim)"
        )
        assert "NGINX_HTTPS_PORT:-8443" not in text, (
            "compose must not default the HTTPS publish to 8443"
        )

    def test_bringup_has_no_pf_or_tailscale_serve(self):
        """bringup.yml must not resurrect the pf rdr shim or tailscale serve:
        cove up can never re-install what the plan deleted."""
        bp = COMPOSE_DIR / "bringup.yml"
        assert bp.exists(), f"bringup.yml not found at {bp}"
        text = bp.read_text()
        assert "rdr-anchor" not in text and "pfctl" not in text, (
            "bringup.yml must not configure pf rdr (443→8443 shim dropped)"
        )
        assert "tailscale serve" not in text, (
            "bringup.yml must not configure tailscale serve (removed with pf shim)"
        )

    def test_bringup_env_render_has_no_dead_https_port_export(self):
        """The .env render must not export NGINX_HTTPS_PORT: the nginx publish
        is hardcoded 0.0.0.0:443:443 in compose, so a stale env value can
        silently diverge from the actual binding."""
        bp = COMPOSE_DIR / "bringup.yml"
        assert bp.exists(), f"bringup.yml not found at {bp}"
        text = bp.read_text()
        assert "NGINX_HTTPS_PORT=" not in text, (
            "bringup.yml env render must not export NGINX_HTTPS_PORT "
            "(compose binds 443 directly; a stale value is a divergence trap)"
        )

    def test_staging_scripts_target_443(self):
        """The staging harness must probe/point at 127.0.0.1:443 — nginx owns
        443 directly and no longer publishes 8443."""
        staging = PROJECT_ROOT / "scripts" / "staging"
        for name in ("setup.sh", "deploy.sh", "e2e.sh"):
            text = (staging / name).read_text()
            assert "8443" not in text, (
                f"scripts/staging/{name} must not reference 8443 "
                "(nginx no longer publishes it)"
            )
            assert "127.0.0.1:443" in text, (
                f"scripts/staging/{name} must target 127.0.0.1:443"
            )

    def test_e2e_staging_tests_target_443(self):
        """Staging/e2e-marked tests must hit 127.0.0.1:443, not the dropped
        8443 publish. This guard's own file (test_cli.py) carries the literal
        '8443' only inside its assertion messages, so it is excluded."""
        tests_dir = PROJECT_ROOT / "cli" / "tests"
        offenders = []
        for path in sorted(tests_dir.glob("test_*.py")):
            if path.name == "test_cli.py":
                continue
            if "8443" in path.read_text():
                offenders.append(path.name)
        assert not offenders, (
            f"test files still reference 8443: {offenders} "
            "(nginx owns 443 directly)"
        )

    def test_tailscale_tasks_safe_when_daemon_dead(self):
        """All tailscale tasks must survive `tailscale status --json` returning {}."""
        bp = COMPOSE_DIR / "bringup.yml"
        with open(bp) as f:
            data = yaml.safe_load(f)

        tasks = data[0]["tasks"] if isinstance(data, list) else data.get("tasks", [])
        tailscale_tasks = [
            t for t in tasks
            if isinstance(t, dict) and "tailscale" in (t.get("name", "") or "").lower()
        ]
        assert tailscale_tasks, "No tailscale tasks found"

        for task in tailscale_tasks:
            name = task.get("name", "")
            # Every set_fact expression that accesses .Self must use | default() guard
            expr = task.get("ansible.builtin.set_fact", {})
            for k, v in expr.items():
                if isinstance(v, str) and ".Self." in v:
                    has_guard = "| default(" in v
                    assert has_guard, (
                        f"Task '{name}' accesses .Self without | default() guard: {v}"
                    )

            # Every when expression that accesses .Self must guard against Self is none
            when = task.get("when")
            if when and ".Self." in str(when):
                when_str = str(when)
                has_self_guard = "Self is not none" in when_str or "Self is none" in when_str
                assert has_self_guard, (
                    f"Task '{name}' when expression accesses .Self without 'Self is not none' guard: {when_str}"
                )

    def test_provision_forgejo_has_autodetect_manual_merge(self):
        pf = COMPOSE_DIR / "provision_forgejo.yml"
        assert pf.exists(), f"provision_forgejo.yml not found at {pf}"

        with open(pf) as f:
            data = yaml.safe_load(f)

        tasks = (data[0] if isinstance(data, list) else data).get("tasks", [])
        merge_task = [
            t for t in tasks
            if isinstance(t, dict)
            and t.get("name") == "Enable autodetect manual merge on repo"
        ]
        assert merge_task, (
            "Missing 'Enable autodetect manual merge on repo' task in provision_forgejo.yml"
        )
        task = merge_task[0]
        body = task.get("ansible.builtin.uri", {}).get("body", {})
        assert body.get("autodetect_manual_merge") is True, (
            "autodetect_manual_merge should be true in provision task"
        )

    def test_provision_forgejo_no_bare_op(self):
        """provision_forgejo.yml must not call bare 'op' directly — biometric prompt spam."""
        pf = COMPOSE_DIR / "provision_forgejo.yml"
        assert pf.exists(), f"provision_forgejo.yml not found at {pf}"

        with open(pf) as f:
            tasks = yaml.safe_load(f)[0]["tasks"]

        for task in tasks:
            if not isinstance(task, dict):
                continue
            name = task.get("name", "")
            uri_module = task.get("ansible.builtin.uri", {})
            cmd = task.get("ansible.builtin.command", {})
            argv = cmd.get("argv", []) if isinstance(cmd, dict) else []
            if isinstance(argv, list) and len(argv) > 0:
                argv_str = " ".join(str(a) for a in argv)
                has_bare_op = (
                    argv[0] == "op"
                    and "op run" not in argv_str
                )
                assert not has_bare_op, (
                    f"Task '{name}' calls bare 'op' — use 'cove creds batch-pull' + local cache instead"
                )


class TestFindComposeDir:
    def test_finds_compose_from_cwd(self, tmp_path, monkeypatch):
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")
        monkeypatch.delenv("COVE_COMPOSE_DIR", raising=False)

        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path), patch(
            "subprocess.run"
        ) as mock_run:
            mock_run.return_value.returncode = 1
            result = resolve_compose_dir()
            assert result == compose_sub

    def test_finds_via_git_root(self, tmp_path, monkeypatch):
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")
        nested = tmp_path / "a" / "b" / "c"
        nested.mkdir(parents=True)
        monkeypatch.delenv("COVE_COMPOSE_DIR", raising=False)

        with patch.object(cove.cli.Path, "cwd", return_value=nested), patch(
            "subprocess.run"
        ) as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = str(tmp_path) + "\n"

            result = resolve_compose_dir()
            assert result == compose_sub

    def test_raises_when_not_found(self, tmp_path, monkeypatch):
        monkeypatch.delenv("COVE_COMPOSE_DIR", raising=False)
        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path), patch(
            "subprocess.run"
        ) as mock_run, patch(
            "cove.stateless.Path.home", return_value=tmp_path
        ):
            mock_run.return_value.returncode = 1
            mock_run.return_value.stderr = "not a git repo"

            with pytest.raises(Exception, match="Run `cove init` first"):
                resolve_compose_dir()

    def test_handles_worktree_path(self, tmp_path, monkeypatch):
        wt = tmp_path / ".worktrees" / str(tmp_path.name)
        compose_sub = wt / "compose"
        compose_sub.mkdir(parents=True)
        (compose_sub / "inventory.yml").write_text("---\n")
        monkeypatch.delenv("COVE_COMPOSE_DIR", raising=False)

        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path), patch(
            "subprocess.run"
        ) as mock_run:
            mock_run.return_value.returncode = 1
            result = resolve_compose_dir()
            assert result == compose_sub


class TestCoveUpCommand:
    @pytest.fixture(autouse=True)
    def _isolate_installed_resources(self, isolated_compose_resources):
        # The up callback calls ensure_init even with --no-upgrade. Both
        # resource entry points are patched and Path.home points into tmp_path.
        return isolated_compose_resources

    def test_up_passes_stable_ansible_hostname_override(self, tmp_path, monkeypatch, _fake_ansible_popen):
        """cove up must pass `-e ansible_hostname=<stable>` so Ansible's
        gathered fact (kernel hostname) cannot diverge from the stable hostname
        used for cert SANs, host_vars, and 1Password op_refs. Without this
        override, cert validation looks for the drifted kernel hostname while
        the cert (and provisioned items) use the stable name, failing `cove up`."""
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")
        (compose_sub / "bringup.yml").write_text("---\n")

        host_vars_file = tmp_path / "state" / "hosts" / "stable-host.yml"
        host_vars_file.parent.mkdir(parents=True)

        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path), patch(
            "subprocess.run"
        ) as mock_run, patch("cove.cli.getpass.getpass", return_value="secret"), patch(
            "cove.cli.ensure_host_vars", return_value=host_vars_file
        ), patch("cove.status.check_all") as mock_check, patch(
            "cove.cli._detect_running_optional_profiles", return_value=[]
        ):
            mock_run.return_value.returncode = 0
            mock_check.return_value = []

            _invoke_callback("up", no_provision=True, no_upgrade=True, all_=False, log=False)

            bringup_call = _fake_ansible_popen["calls"][0]
            bringup_args = [str(a) for a in bringup_call]
            assert any(
                a == "-e" or a.startswith("ansible_hostname=") for a in bringup_args
            ), "cove up must pass an -e ansible_hostname extra var"
            hostname_override = next(
                a for a in bringup_args if a.startswith("ansible_hostname=")
            )
            assert hostname_override == "ansible_hostname=stable-host", (
                f"ansible_hostname must match the host_vars stem (stable), "
                f"got: {hostname_override}"
            )

    def test_up_no_become_prompt_per_playbook(self, tmp_path, monkeypatch, _fake_ansible_popen):
        """cove up must NOT pass -K to ansible-playbook — it caches the BECOME
        password once via getpass and passes it via ANSIBLE_BECOME_PASSWORD env."""
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")
        (compose_sub / "bringup.yml").write_text("---\n")

        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path), patch(
            "subprocess.run"
        ) as mock_run, patch(
            "cove.cli.ensure_host_vars", return_value=tmp_path / "nonexistent.yml"
        ), patch("cove.status.check_all") as mock_check, patch(
            "cove.cli._detect_running_optional_profiles", return_value=[]
        ), patch("cove.cli.getpass.getpass", return_value="secret"):
            mock_run.return_value.returncode = 0
            mock_check.return_value = []

            _invoke_callback("up", no_provision=True, no_upgrade=True, all_=False, log=False)

            bringup_call = _fake_ansible_popen["calls"][0]
            args_list = [str(a) for a in bringup_call]
            assert "-K" not in args_list, (
                "cove up must not pass -K (uses ANSIBLE_BECOME_PASSWORD env var instead)"
            )

    def test_up_prompts_become_password_once(self, tmp_path, monkeypatch):
        """cove up must prompt for the BECOME password exactly once (via
        getpass), not once per ansible-playbook invocation."""
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")
        (compose_sub / "bringup.yml").write_text("---\n")
        (compose_sub / "bootstrap_vault.yml").write_text("---\n")
        (compose_sub / "provision_vault_user.yml").write_text("---\n")
        (compose_sub / "provision_forgejo.yml").write_text("---\n")

        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path), patch(
            "subprocess.run"
        ) as mock_run, patch(
            "cove.cli.ensure_host_vars", return_value=tmp_path / "nonexistent.yml"
        ), patch("cove.status.check_all") as mock_check, patch(
            "cove.cli._detect_running_optional_profiles", return_value=[]
        ), patch("cove.cli.getpass.getpass", return_value="secret") as mock_getpass:
            mock_run.return_value.returncode = 0
            mock_check.return_value = []

            _invoke_callback("up", no_provision=False, no_upgrade=True, all_=False, log=False)

            assert mock_getpass.call_count == 1, (
                f"BECOME password must be prompted once, got {mock_getpass.call_count}"
            )

    def test_no_provision_skips_forgejo(self, tmp_path, monkeypatch, _fake_ansible_popen):
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")
        (compose_sub / "bringup.yml").write_text("---\n")

        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path), patch(
            "subprocess.run"
        ) as mock_run, patch("cove.cli.getpass.getpass", return_value="secret"), patch(
            "cove.cli.ensure_host_vars", return_value=tmp_path / "nonexistent.yml"
        ), patch("cove.status.check_all") as mock_check, patch(
            "cove.cli._detect_running_optional_profiles", return_value=[]
        ):
            mock_run.return_value.returncode = 0
            mock_check.return_value = []

            _invoke_callback("up", no_provision=True, no_upgrade=True, all_=False, log=False)
            assert len(_fake_ansible_popen["calls"]) == 1, (
                "no-provision up must run exactly one playbook (bringup)"
            )
            assert any(
                "bringup.yml" in str(p) for p in _fake_ansible_popen["calls"][0]
            )

    def test_full_up_calls_all_in_correct_order(self, tmp_path, monkeypatch, _fake_ansible_popen):
        """Batch-pull must come first, then bringup, then vault bootstrap, then provision."""
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")
        (compose_sub / "bringup.yml").write_text("---\n")
        (compose_sub / "bootstrap_vault.yml").write_text("---\n")
        (compose_sub / "provision_vault_user.yml").write_text("---\n")
        (compose_sub / "provision_forgejo.yml").write_text("---\n")

        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path), patch(
            "subprocess.run"
        ) as mock_run, patch("cove.cli.getpass.getpass", return_value="secret"), patch(
            "cove.cli.ensure_host_vars", return_value=tmp_path / "nonexistent.yml"
        ), patch("cove.status.check_all") as mock_check, patch(
            "cove.cli._detect_running_optional_profiles", return_value=[]
        ):
            mock_run.return_value.returncode = 0
            mock_check.return_value = []

            _invoke_callback("up", no_provision=False, no_upgrade=True, all_=False, log=False)
            playbooks = [
                next(str(p) for p in reversed(cmd) if str(p).endswith(".yml"))
                for cmd in _fake_ansible_popen["calls"]
            ]
            run_cmds = [str(c[0][0]) for c in mock_run.call_args_list]

            assert len(playbooks) == 4, (
                f"full up must run 4 playbooks, got: {playbooks}"
            )
            assert run_cmds and "batch-pull" in run_cmds[0], (
                "batch-pull (subprocess.run) must come first"
            )
            # The only other subprocess.run calls in the full up flow are the
            # Vault runtime-state snapshots (read-only `docker inspect` of the
            # container Id/StartedAt, taken before bringup and after the
            # stale-bind restart step). They are not provisioning steps:
            # batch-pull stays the only non-docker subprocess call.
            non_docker = [c for c in run_cmds if not c.startswith("['docker'")]
            assert non_docker == ["['cove', 'creds', 'batch-pull']"], (
                f"batch-pull must be the only non-docker subprocess.run "
                f"call, got: {non_docker}"
            )

            def _occurred(cmd_name: str) -> bool:
                return any(cmd_name in p for p in playbooks)

            order = [
                playbooks.index(next(p for p in playbooks if "bringup.yml" in p)),
                playbooks.index(next(p for p in playbooks if "bootstrap_vault.yml" in p)),
                playbooks.index(next(p for p in playbooks if "provision_vault_user.yml" in p)),
                playbooks.index(next(p for p in playbooks if "provision_forgejo.yml" in p)),
            ]
            assert order == sorted(order), (
                f"playbook order must be bringup, bootstrap_vault, "
                f"provision_vault_user, provision_forgejo; got: {playbooks}"
            )
            assert _occurred("bringup.yml")
            assert _occurred("bootstrap_vault.yml")
            assert _occurred("provision_vault_user.yml")
            assert _occurred("provision_forgejo.yml")

    def test_up_passes_running_optional_profiles_to_bringup(self, tmp_path, monkeypatch, _fake_ansible_popen):
        """cove up must detect running optional services and pass their compose
        profiles to bringup.yml so they get reconciled (recreated with current
        config). Stopped optionals must NOT be started."""
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")
        (compose_sub / "bringup.yml").write_text("---\n")

        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path), patch(
            "subprocess.run"
        ) as mock_run, patch("cove.cli.getpass.getpass", return_value="secret"), patch(
            "cove.cli.ensure_host_vars", return_value=tmp_path / "nonexistent.yml"
        ), patch("cove.status.check_all") as mock_check, patch(
            "cove.cli._detect_running_optional_profiles", return_value=["speedtest"]
        ) as mock_detect:
            mock_run.return_value.returncode = 0
            mock_check.return_value = []

            _invoke_callback("up", no_provision=True, no_upgrade=True, all_=False, log=False)

            mock_detect.assert_called_once()
            bringup_call = _fake_ansible_popen["calls"][0]
            bringup_args = [str(a) for a in bringup_call]
            assert any("bringup.yml" in a for a in bringup_args), (
                "first call must be bringup.yml"
            )
            assert any("cove_profiles" in a and "speedtest" in a for a in bringup_args), (
                f"bringup must receive cove_profiles=speedtest, got: {bringup_args}"
            )

    def test_up_no_profiles_when_no_optionals_running(self, tmp_path, monkeypatch, _fake_ansible_popen):
        """When no optional services are running, cove up must not pass any
        profiles (so it doesn't start stopped optionals)."""
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")
        (compose_sub / "bringup.yml").write_text("---\n")

        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path), patch(
            "subprocess.run"
        ) as mock_run, patch("cove.cli.getpass.getpass", return_value="secret"), patch(
            "cove.cli.ensure_host_vars", return_value=tmp_path / "nonexistent.yml"
        ), patch("cove.status.check_all") as mock_check, patch(
            "cove.cli._detect_running_optional_profiles", return_value=[]
        ):
            mock_run.return_value.returncode = 0
            mock_check.return_value = []

            _invoke_callback("up", no_provision=True, no_upgrade=True, all_=False, log=False)

            bringup_call = _fake_ansible_popen["calls"][0]
            bringup_args = [str(a) for a in bringup_call]
            assert not any("speedtest" in a for a in bringup_args), (
                f"no profiles when nothing running, got: {bringup_args}"
            )

    def test_up_all_passes_runner_to_bringup(self, tmp_path, monkeypatch, _fake_ansible_popen):
        """cove up --all must include the runner profile in the bringup
        COMPOSE_PROFILES (no credential dance for the runner). Litellm and
        speedtest must NOT be in it: their containers need CLI-prepared
        credentials first, so they start through their own flows right after
        the provisioning chain. ADE is core since 0.8.0 — no profile."""
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")
        (compose_sub / "bringup.yml").write_text("---\n")

        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path), patch(
            "subprocess.run"
        ) as mock_run, patch("cove.cli.getpass.getpass", return_value="secret"), patch(
            "cove.cli.ensure_host_vars", return_value=tmp_path / "nonexistent.yml"
        ), patch("cove.status.check_all") as mock_check, patch(
            "cove.cli._detect_running_optional_profiles", return_value=[]
        ):
            mock_run.return_value.returncode = 0
            mock_check.return_value = []

            _invoke_callback(
                "up", no_provision=True, no_upgrade=True, all_=True, log=False
            )

            bringup_call = _fake_ansible_popen["calls"][0]
            bringup_args = [str(a) for a in bringup_call]
            assert any("cove_profiles=runner" in a for a in bringup_args), (
                f"bringup must receive cove_profiles=runner, got: {bringup_args}"
            )
            assert not any("ade" in a for a in bringup_args), (
                f"ADE is core (no profile) — must not appear in profiles, got: {bringup_args}"
            )

    def test_up_all_starts_litellm_and_speedtest_after_bringup(
        self, tmp_path, monkeypatch
    ):
        """cove up --all must run the litellm and speedtest up flows after the
        bringup (they prepare credentials, then start their containers)."""
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")
        (compose_sub / "bringup.yml").write_text("---\n")

        calls = []
        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path), patch(
            "subprocess.run"
        ) as mock_run, patch("cove.cli.getpass.getpass", return_value="secret"), patch(
            "cove.cli.ensure_host_vars", return_value=tmp_path / "nonexistent.yml"
        ), patch("cove.status.check_all") as mock_check, patch(
            "cove.cli._detect_running_optional_profiles", return_value=[]
        ), patch.object(
            cove.litellm.litellm.commands["up"],
            "callback",
            side_effect=lambda: calls.append("litellm"),
        ), patch.object(
            cove.speedtest.speedtest.commands["up"],
            "callback",
            side_effect=lambda: calls.append("speedtest"),
        ):
            mock_run.return_value.returncode = 0
            mock_check.return_value = []

            _invoke_callback(
                "up", no_provision=True, no_upgrade=True, all_=True, log=False
            )

            assert calls == ["litellm", "speedtest"], (
                f"litellm and speedtest up flows must run after bringup, got: {calls}"
            )

    def test_up_all_tolerates_optional_service_failure(self, tmp_path, monkeypatch):
        """A credential failure on one optional service must not abort
        `cove up --all` — optional services stay optional (same contract as
        `cove status`). The remaining service flow and the status check must
        still run."""
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")
        (compose_sub / "bringup.yml").write_text("---\n")

        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path), patch(
            "subprocess.run"
        ) as mock_run, patch("cove.cli.getpass.getpass", return_value="secret"), patch(
            "cove.cli.ensure_host_vars", return_value=tmp_path / "nonexistent.yml"
        ), patch("cove.status.check_all") as mock_check, patch(
            "cove.cli._detect_running_optional_profiles", return_value=[]
        ), patch.object(
            cove.litellm.litellm.commands["up"],
            "callback",
            side_effect=click.ClickException("Cove Admin item missing"),
        ), patch.object(
            cove.speedtest.speedtest.commands["up"], "callback"
        ) as mock_speedtest:
            mock_run.return_value.returncode = 0
            mock_check.return_value = []

            _invoke_callback(
                "up", no_provision=True, no_upgrade=True, all_=True, log=False
            )

            mock_speedtest.assert_called_once()
            mock_check.assert_called_once()

    def test_bringup_failure_reports_readable_error(self, tmp_path, monkeypatch, capsys, _fake_ansible_popen):
        """An ansible playbook failure must print a friendly report (origin,
        problem, log path) instead of Ansible's raw fatal dump, write a log
        file even without --log, and exit with Ansible's return code."""
        out = [
            "PLAY [all] ********",
            "TASK [Fail if a non-empty directory wedges a data-root mount] ***",
            'fatal: [localhost] (item=/Users/x/cove-data/toolhive/registry.json): '
            '{"msg": "registry.json exists as a NON-EMPTY DIRECTORY. '
            'Remove it and re-run: rm -rf /Users/x/cove-data/toolhive/registry.json && cove up", "changed": false}',
            "Origin: /Users/cove/compose/bringup.yml:439:7",
            "NO MORE HOSTS LEFT",
            "PLAY RECAP",
        ]
        _fake_ansible_popen["returncode"] = 2
        _fake_ansible_popen["out"] = out
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")
        (compose_sub / "bringup.yml").write_text("---\n")

        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path), patch(
            "cove.cli.getpass.getpass", return_value="secret"
        ), patch("cove.cli.ensure_host_vars", return_value=tmp_path / "hv.yml"), patch(
            "cove.cli._detect_running_optional_profiles", return_value=[]
        ), patch("cove.cli.Path.home", return_value=tmp_path):
            with pytest.raises(SystemExit) as exc:
                _invoke_callback("up", no_provision=True, no_upgrade=True, all_=False, log=False)
        assert exc.value.code == 2

        err = capsys.readouterr().err
        assert "Ansible play failed: bringup.yml" in err, f"missing failure header, got: {err}"
        assert "Origin:" in err, "report must include the failing task's origin"
        assert "NON-EMPTY DIRECTORY" in err, "report must include the error message"
        assert "rm -rf" in err and "cove up" in err, "report must surface the suggested fix"
        assert "Full log:" in err, "report must point at the log file"

        import re as _re
        log_path = _re.search(r"Full log: (.+)", err).group(1).strip()
        assert Path(log_path).exists(), "failure log must be written even without --log"
        assert "NON-EMPTY DIRECTORY" in Path(log_path).read_text()

    def test_ansible_failure_unknown_shape_prints_output_tail(self, tmp_path, monkeypatch, capsys, _fake_ansible_popen):
        """When the failure output has no parseable Origin/msg markers, the
        report must fall back to showing the tail of the raw output and the
        log path, never a bare exit with no explanation."""
        _fake_ansible_popen["returncode"] = 4
        _fake_ansible_popen["out"] = ["ERROR! something exploded", "more context"]

        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")
        (compose_sub / "bringup.yml").write_text("---\n")

        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path), patch(
            "cove.cli.getpass.getpass", return_value="secret"
        ), patch("cove.cli.ensure_host_vars", return_value=tmp_path / "hv.yml"), patch(
            "cove.cli._detect_running_optional_profiles", return_value=[]
        ):
            with pytest.raises(SystemExit):
                _invoke_callback("up", no_provision=True, no_upgrade=True, all_=False, log=False)

        err = capsys.readouterr().err
        assert "Ansible play failed: bringup.yml" in err
        assert "Last output:" in err and "something exploded" in err
        assert "Full log:" in err


    def test_up_skips_become_prompt_when_passwordless(self, tmp_path, monkeypatch, _fake_ansible_popen):
        """After `cove sudo enable`, cove up must not prompt for the BECOME
        password (getpass is called zero times)."""
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")
        (compose_sub / "bringup.yml").write_text("---\n")
        monkeypatch.setattr("cove.cli.passwordless_sudo_ok", lambda: True)

        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path), patch(
            "cove.cli.getpass.getpass"
        ) as mock_getpass, patch(
            "cove.cli.ensure_host_vars", return_value=tmp_path / "nonexistent.yml"
        ), patch("cove.status.check_all", return_value=[]), patch(
            "cove.cli._detect_running_optional_profiles", return_value=[]
        ):
            _invoke_callback("up", no_provision=True, no_upgrade=True, all_=False, log=False)

        mock_getpass.assert_not_called()

    def test_up_passes_typed_become_password_via_ansible_become_pass_env(
        self, tmp_path, monkeypatch, _fake_ansible_popen
    ):
        """A typed BECOME password must reach sudo through ANSIBLE_BECOME_PASS,
        the env var the ansible-core sudo become plugin actually reads
        (sudo.py DOCUMENTATION). ANSIBLE_BECOME_PASSWORD matches no ansible
        setting, so the typed password was silently dropped and every become
        task failed with 'sudo: a password is required'."""
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")
        (compose_sub / "bringup.yml").write_text("---\n")
        # Fixture default: passwordless_sudo_ok() is False → prompt path.

        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path), patch(
            "cove.cli.getpass.getpass", return_value="secret"
        ), patch("cove.cli.ensure_host_vars", return_value=tmp_path / "hv.yml"), patch(
            "cove.status.check_all", return_value=[]
        ), patch("cove.cli._detect_running_optional_profiles", return_value=[]):
            _invoke_callback("up", no_provision=True, no_upgrade=True, all_=False, log=False)

        assert _fake_ansible_popen["envs"], "Popen must receive an env"
        for env in _fake_ansible_popen["envs"]:
            if not env:
                continue
            assert env.get("ANSIBLE_BECOME_PASS") == "secret"
            assert "ANSIBLE_BECOME_PASSWORD" not in env

    def test_up_sets_empty_ansible_become_pass_when_passwordless(
        self, tmp_path, monkeypatch, _fake_ansible_popen
    ):
        """With the passwordless drop-in in place, ANSIBLE_BECOME_PASS is set
        empty (falsy to the sudo plugin, so no password is ever handed to
        sudo)."""
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")
        (compose_sub / "bringup.yml").write_text("---\n")
        monkeypatch.setattr("cove.cli.passwordless_sudo_ok", lambda: True)

        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path), patch(
            "cove.cli.getpass.getpass"
        ) as mock_getpass, patch(
            "cove.cli.ensure_host_vars", return_value=tmp_path / "hv.yml"
        ), patch("cove.status.check_all", return_value=[]), patch(
            "cove.cli._detect_running_optional_profiles", return_value=[]
        ):
            _invoke_callback("up", no_provision=True, no_upgrade=True, all_=False, log=False)

        mock_getpass.assert_not_called()
        assert _fake_ansible_popen["envs"], "Popen must receive an env"
        for env in _fake_ansible_popen["envs"]:
            if not env:
                continue
            assert env.get("ANSIBLE_BECOME_PASS") == ""
            assert "ANSIBLE_BECOME_PASSWORD" not in env


class TestCoveStatusCommand:
    def test_status_all_ok(self, tmp_path, monkeypatch):
        with patch("cove.status._check_containers") as mock_containers, patch(
            "cove.status._check_nginx_ingress"
        ) as mock_nginx, patch(
            "cove.status._check_forgejo"
        ) as mock_forgejo, patch(
            "cove.status._check_vault"
        ) as mock_vault, patch(
            "cove.status._check_dns"
        ) as mock_dns, patch(
            "cove.status._check_resolver_port", return_value=None
        ):
            from cove.status import CheckResult
            mock_containers.return_value = [
                CheckResult(name="Forgejo", ok=True, detail="Up 2 hours"),
                CheckResult(name="nginx", ok=True, detail="Up 2 hours"),
                CheckResult(name="Vault", ok=True, detail="Up 2 hours (healthy)"),
                CheckResult(name="dnsmasq", ok=True, detail="Up 2 hours"),
                CheckResult(name="dnsproxy", ok=True, detail="Up 2 hours"),
            ]
            mock_nginx.return_value = CheckResult(name="nginx ingress", ok=True, detail="cove ingress ok")
            mock_forgejo.return_value = CheckResult(name="Forgejo API", ok=True, detail="ok")
            mock_vault.return_value = CheckResult(name="Vault API", ok=True, detail="initialized, unsealed")
            mock_dns.return_value = CheckResult(name="DNS resolution", ok=True, detail="git.cove.local → 127.0.0.1")

            runner = CliRunner()
            result = runner.invoke(cove.cli.app, ["status"])
            assert result.exit_code == 0, result.output
            assert "5/5" in result.output or "9/9" in result.output

    def test_status_fails_on_container_down(self, tmp_path, monkeypatch):
        with patch("cove.status._check_containers") as mock_containers, patch(
            "cove.status._check_nginx_ingress"
        ) as mock_nginx, patch(
            "cove.status._check_forgejo"
        ) as mock_forgejo, patch(
            "cove.status._check_vault"
        ) as mock_vault, patch(
            "cove.status._check_dns"
        ) as mock_dns, patch(
            "cove.status._check_resolver_port", return_value=None
        ):
            from cove.status import CheckResult
            mock_containers.return_value = [
                CheckResult(name="Forgejo", ok=False, detail="Container cove-forgejo is not running",
                            hints=["Run `docker compose ... up -d forgejo`"]),
            ]
            mock_nginx.return_value = CheckResult(name="nginx ingress", ok=True, detail="cove ingress ok")
            mock_forgejo.return_value = CheckResult(name="Forgejo API", ok=True, detail="ok")
            mock_vault.return_value = CheckResult(name="Vault API", ok=True, detail="initialized, unsealed")
            mock_dns.return_value = CheckResult(name="DNS resolution", ok=True, detail="git.cove.local → 127.0.0.1")

            runner = CliRunner()
            result = runner.invoke(cove.cli.app, ["status"])
            assert result.exit_code != 0, "status should fail when a container is down"
            assert "✗" in result.output

    def test_status_optional_not_running_shows_launch_hint(self):
        """A stopped optional service must show as not-ok with a launch hint,
        not a green ✓. The operator should see what's off and how to start it."""
        from cove.status import _check_containers, CheckResult
        with patch("cove.status._docker_ps", return_value={}):
            results = _check_containers()
        optional_results = [r for r in results if r.name == "Speedtest"]
        assert optional_results, "Speedtest should be in results"
        r = optional_results[0]
        assert not r.ok, (
            f"stopped optional service must be ok=False, got ok={r.ok}: {r.detail}"
        )
        assert r.hints, (
            f"stopped optional service must have a launch hint, got hints={r.hints}"
        )
        assert any("cove speedtest up" in h for h in r.hints), (
            f"launch hint must mention `cove speedtest up`, got: {r.hints}"
        )

    def test_status_stopped_optional_does_not_fail_exit_code(self):
        """A stopped optional service must NOT cause `cove status` to exit
        non-zero — it's legitimately optional, not a failure."""
        with patch("cove.status._check_containers") as mock_containers, patch(
            "cove.status._check_nginx_ingress"
        ) as mock_nginx, patch(
            "cove.status._check_forgejo"
        ) as mock_forgejo, patch(
            "cove.status._check_vault"
        ) as mock_vault, patch(
            "cove.status._check_dns"
        ) as mock_dns, patch(
            "cove.status._check_resolver_port", return_value=None
        ):
            from cove.status import CheckResult
            mock_containers.return_value = [
                CheckResult(name="Forgejo", ok=True, detail="Up"),
                CheckResult(name="nginx", ok=True, detail="Up"),
                CheckResult(name="Vault", ok=True, detail="Up"),
                CheckResult(name="dnsmasq", ok=True, detail="Up"),
                CheckResult(name="dnsproxy", ok=True, detail="Up"),
                CheckResult(name="Speedtest", ok=False, detail="not running (optional)",
                            hints=["Run `cove speedtest up`"], optional=True),
            ]
            mock_nginx.return_value = CheckResult(name="nginx ingress", ok=True, detail="ok")
            mock_forgejo.return_value = CheckResult(name="Forgejo API", ok=True, detail="ok")
            mock_vault.return_value = CheckResult(name="Vault API", ok=True, detail="ok")
            mock_dns.return_value = CheckResult(name="DNS resolution", ok=True, detail="ok")

            runner = CliRunner()
            result = runner.invoke(cove.cli.app, ["status"])
            assert result.exit_code == 0, (
                f"stopped optional must not fail exit code, got {result.exit_code}: {result.output}"
            )

    def test_status_optional_running_shows_ok(self):
        """A running optional service must show as ok=True with its status."""
        from cove.status import _check_containers
        with patch("cove.status._docker_ps", return_value={
            "cove-speedtest-tracker": {"Status": "Up 5 hours (healthy)"},
            "cove-forgejo": {"Status": "Up 5 hours"},
            "cove-nginx": {"Status": "Up 5 hours"},
            "cove-vault": {"Status": "Up 5 hours (healthy)"},
            "cove-dnsmasq": {"Status": "Up 5 hours"},
            "cove-dnsproxy": {"Status": "Up 5 hours"},
        }):
            results = _check_containers()
        r = [x for x in results if x.name == "Speedtest"][0]
        assert r.ok and "Up 5 hours" in r.detail

    def test_resolver_port_check_silent_when_no_drift(self):
        from cove.status import _check_resolver_port

        with patch("cove.status.is_macos", return_value=True), patch(
            "cove.status.resolve_compose_dir", return_value=Path("/tmp/compose")
        ), patch("cove.status.expected_dnsmasq_port", return_value=5354), patch(
            "cove.status.drifted_resolver_files", return_value={}
        ):
            assert _check_resolver_port() is None, (
                "no drift must not add a status row"
            )

    def test_resolver_port_check_fails_loud_with_corrective_command(self):
        from cove.status import _check_resolver_port

        stale = Path("/etc/resolver/cove")
        with patch("cove.status.is_macos", return_value=True), patch(
            "cove.status.resolve_compose_dir", return_value=Path("/tmp/compose")
        ), patch("cove.status.expected_dnsmasq_port", return_value=5354), patch(
            "cove.status.drifted_resolver_files", return_value={stale: 5353}
        ):
            result = _check_resolver_port()
        assert result is not None and not result.ok, (
            "a stale /etc/resolver port must fail status loudly"
        )
        assert "5354" in result.detail
        assert any("port 5354" in hint for hint in result.hints), (
            f"the hint must carry the exact corrective command, got {result.hints}"
        )

    def test_resolver_port_check_skips_non_macos(self):
        from cove.status import _check_resolver_port

        with patch("cove.status.is_macos", return_value=False):
            assert _check_resolver_port() is None

    def test_resolver_port_check_silent_when_expected_port_unknown(self):
        """Without a readable dnsmasq_port there is nothing to compare against;
        the DNS-resolution check still covers a broken resolver."""
        from cove.status import _check_resolver_port

        with patch("cove.status.is_macos", return_value=True), patch(
            "cove.status.resolve_compose_dir", side_effect=RuntimeError("no compose")
        ):
            assert _check_resolver_port() is None


class TestCoveDownCommand:
    def test_down_runs_docker_compose(self, tmp_path, monkeypatch):
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")

        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path), patch(
            "subprocess.run"
        ) as mock_run:
            mock_run.return_value.returncode = 0

            _invoke_callback("down", volumes=False)

            assert mock_run.call_count == 1
            args = [str(a) for a in mock_run.call_args[0][0]]
            assert args[0] == "docker"
            assert "down" in args

    def test_down_with_volumes(self, tmp_path, monkeypatch):
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")

        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path), patch(
            "subprocess.run"
        ) as mock_run:
            mock_run.return_value.returncode = 0

            _invoke_callback("down", volumes=True)

            args = [str(a) for a in mock_run.call_args[0][0]]
            assert "--volumes" in args, "cove down --volumes must pass --volumes to docker compose"


class TestCoveUninstallCommand:
    def test_uninstall_default_prompts_and_only_strips_guidance(self, tmp_path, monkeypatch):
        """Default (no flags): prompts for confirmation, only strips guidance — does NOT touch containers."""
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")
        cache_dir = tmp_path / ".cache" / "cove"
        cache_dir.mkdir(parents=True)
        (cache_dir / "op-cache.json").write_text("{}")

        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text(
            "# My Project\n\n"
            "<!-- cove-guidance start -->\n"
            "## Cove\n\nsome guidance\n"
            "<!-- cove-guidance end -->\n"
        )

        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path), patch(
            "cove.cli.Path.home", return_value=tmp_path
        ), patch("subprocess.run") as mock_run, patch("shutil.rmtree") as mock_rmtree:
            mock_run.return_value.returncode = 0

            runner = CliRunner()
            result = runner.invoke(cove.cli.app, ["uninstall"], input="y\n")

            assert result.exit_code == 0
            assert "guidance" in result.output.lower()
            compose_down_calls = [
                c for c in mock_run.call_args_list
                if "compose" in str(c[0][0][:3])
            ]
            assert len(compose_down_calls) == 0, (
                "default uninstall must not run docker compose down"
            )
            mock_rmtree.assert_not_called(), (
                "default uninstall must not remove cache dir"
            )

        remaining = agents_md.read_text()
        assert "cove-guidance" not in remaining
        assert "# My Project" in remaining

    def test_uninstall_default_aborts_on_no(self, tmp_path, monkeypatch):
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")

        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path):
            runner = CliRunner()
            result = runner.invoke(cove.cli.app, ["uninstall"], input="n\n")
            assert result.exit_code != 0, "uninstall without confirmation must abort"

    def test_uninstall_force_skips_prompt_strips_guidance(self, tmp_path, monkeypatch):
        """-f without --all: skips prompt, only strips guidance."""
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")
        cache_dir = tmp_path / ".cache" / "cove"
        cache_dir.mkdir(parents=True)
        (cache_dir / "op-cache.json").write_text("{}")

        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text(
            "# My Project\n\n"
            "<!-- cove-guidance start -->\n"
            "## Cove\n\nsome guidance\n"
            "<!-- cove-guidance end -->\n"
        )

        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path), patch(
            "cove.cli.Path.home", return_value=tmp_path
        ), patch("subprocess.run") as mock_run, patch("shutil.rmtree") as mock_rmtree:
            mock_run.return_value.returncode = 0

            runner = CliRunner()
            result = runner.invoke(cove.cli.app, ["uninstall", "-f"])

            assert result.exit_code == 0
            compose_down_calls = [
                c for c in mock_run.call_args_list
                if "compose" in str(c[0][0][:3])
            ]
            assert len(compose_down_calls) == 0, (
                "-f without --all must not run docker compose down"
            )
            mock_rmtree.assert_not_called()

        remaining = agents_md.read_text()
        assert "cove-guidance" not in remaining

    def test_uninstall_all_stops_containers_and_strips_guidance(self, tmp_path, monkeypatch):
        """--all -f: stops containers, removes credentials, strips guidance."""
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")
        cache_dir = tmp_path / ".cache" / "cove"
        cache_dir.mkdir(parents=True)
        (cache_dir / "op-cache.json").write_text("{}")

        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path), patch(
            "cove.cli.Path.home", return_value=tmp_path
        ), patch("subprocess.run") as mock_run, patch("shutil.rmtree"):
            mock_run.return_value.returncode = 0

            _invoke_callback("uninstall", all_=True, force=True, global_=False)

            compose_down_calls = [
                c for c in mock_run.call_args_list
                if "compose" in str(c[0][0][:3])
            ]
            assert len(compose_down_calls) >= 1, (
                "--all must run docker compose down"
            )

    def test_uninstall_all_prompts_without_force(self, tmp_path, monkeypatch):
        """--all without -f: prompts for confirmation."""
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")

        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path), patch(
            "cove.cli.Path.home", return_value=tmp_path
        ), patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0

            runner = CliRunner()
            result = runner.invoke(cove.cli.app, ["uninstall", "--all"], input="n\n")

            assert result.exit_code != 0, "--all without -f must prompt and abort on no"
            compose_down_calls = [
                c for c in mock_run.call_args_list
                if "compose" in str(c[0][0][:3])
            ]
            assert len(compose_down_calls) == 0, (
                "--all aborted must not run docker compose down"
            )

    def test_uninstall_no_project_dir_exits_cleanly(self, tmp_path, monkeypatch):
        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path):
            runner = CliRunner()
            with patch("cove.cli.resolve_compose_dir", side_effect=click.ClickException("no project")):
                result = runner.invoke(cove.cli.app, ["uninstall", "-f"])
            assert result.exit_code != 0, "uninstall with no compose dir should fail"

    def test_uninstall_all_strips_cove_guidance_from_agents_md(self, tmp_path, monkeypatch):
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")

        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text(
            "# My Project\n\n"
            "<!-- cove-guidance start -->\n"
            "## Cove\n\nsome guidance\n"
            "<!-- cove-guidance end -->\n"
        )

        with patch("cove.cli.Path.home", return_value=tmp_path), patch(
            "subprocess.run"
        ) as mock_run, patch("shutil.rmtree"), patch.object(cove.cli.Path, "cwd", return_value=tmp_path):
            mock_run.return_value.returncode = 0

            _invoke_callback("uninstall", all_=True, force=True, global_=False)

            remaining = agents_md.read_text()
            assert "cove-guidance" not in remaining
            assert "# My Project" in remaining

    def test_uninstall_all_removes_agents_md_if_only_guidance(self, tmp_path, monkeypatch):
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")

        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text(
            "<!-- cove-guidance start -->\n"
            "## Cove\n\nsome guidance\n"
            "<!-- cove-guidance end -->\n"
        )

        with patch("cove.cli.Path.home", return_value=tmp_path), patch(
            "subprocess.run"
        ) as mock_run, patch("shutil.rmtree"), patch.object(cove.cli.Path, "cwd", return_value=tmp_path):
            mock_run.return_value.returncode = 0

            _invoke_callback("uninstall", all_=True, force=True, global_=False)

        assert not agents_md.exists(), "AGENTS.md with only guidance should be deleted"


class TestProjectUninstall:
    def test_strip_removes_guidance_block(self, tmp_path):
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text(
            "# My Project\n\n"
            "<!-- cove-guidance start -->\n"
            "## Cove\n\nsome guidance\n"
            "<!-- cove-guidance end -->\n"
        )
        _strip(agents_md)
        remaining = agents_md.read_text()
        assert "cove-guidance" not in remaining
        assert "# My Project" in remaining

    def test_strip_deletes_file_if_only_guidance(self, tmp_path):
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text(
            "<!-- cove-guidance start -->\n"
            "## Cove\n\nsome guidance\n"
            "<!-- cove-guidance end -->\n"
        )
        _strip(agents_md)
        assert not agents_md.exists()

    def test_strip_noop_if_no_guidance(self, tmp_path):
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text("# Just project notes\n")
        _strip(agents_md)
        assert agents_md.read_text() == "# Just project notes\n"

    def test_strip_noop_if_file_missing(self, tmp_path):
        agents_md = tmp_path / "AGENTS.md"
        _strip(agents_md)
        assert not agents_md.exists()

    def test_inject_then_strip_roundtrip(self, tmp_path):
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text("# My Project\n")
        rendered = "## Cove\n\nForgejo at localhost\n"
        _inject(agents_md, rendered)
        assert SENTINEL_START in agents_md.read_text()
        _strip(agents_md)
        assert agents_md.read_text().strip() == "# My Project"


class TestProgressiveDisclosure:
    def test_write_detail_cove_creates_file_with_content(self, tmp_path):
        detail = tmp_path / "agents-md-detail" / "cove.md"
        _write_detail_cove(detail, "## Cove\n\nForgejo info here")
        assert detail.exists()
        content = detail.read_text()
        assert "Forgejo info here" in content

    def test_write_detail_cove_no_trailing_blank_line(self, tmp_path):
        detail = tmp_path / "cove.md"
        _write_detail_cove(detail, "some content\n")
        assert detail.read_text() == "some content\n"

    def test_remove_detail_cove_deletes_existing_file(self, tmp_path):
        detail = tmp_path / "cove.md"
        detail.write_text("content")
        _remove_detail_cove(detail)
        assert not detail.exists()

    def test_remove_detail_cove_noop_when_missing(self, tmp_path):
        detail = tmp_path / "nonexistent.md"
        _remove_detail_cove(detail)
        assert not detail.exists()

    def test_fj_spoke_doc_includes_issue_commands_and_title_caveat(self, tmp_path):
        """Installed fj.md must document issue creation and warn about --title flag."""
        from importlib.resources import files
        from jinja2 import Environment, BaseLoader

        template_text = files("cove.templates").joinpath("fj-reference.md.j2").read_text()
        rendered = Environment(loader=BaseLoader()).from_string(template_text).render()

        assert "fj issue create" in rendered, (
            "fj-reference.md.j2 must document issue creation commands"
        )
        assert "--title" in rendered, (
            "fj-reference.md.j2 must warn that fj issue create has no --title flag"
        )
        assert "positional argument" in rendered.lower(), (
            "fj-reference.md.j2 must explain title is a positional argument"
        )

    def test_inject_agents_block_contains_cove_info(self, tmp_path):
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text("# Project\n")
        ctx = {
            "forgejo_root_url": "https://example.com:3000/",
            "vault_addr": "http://127.0.0.1:8200",
            "admin_username": "testuser",
            "forgejo_domain": "example.com",
            "forgejo_ssh_domain": "example.com",
            "forgejo_ssh_port": "2222",
        }
        block = _render_agents_block(ctx, ".agents/agents-md-detail/cove.md")
        _inject(agents_md, block)
        content = agents_md.read_text()
        assert SENTINEL_START in content
        assert "git.cove" in content
        assert "Forgejo" in content
        assert "agents-md-detail/cove.md" in content
        assert "Project override" in content
        assert "origin" in content
        assert "secondary remote" in content
        assert "fj" in content
        assert "gh" in content
        assert "gl" in content

    def test_uninstall_strips_guidance_block(self, tmp_path):
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")

        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text(
            "# My Project\n\n"
            "<!-- cove-guidance start -->\n"
            "## Cove\n\n"
            "Full reference in `.agents/agents-md-detail/cove.md`.\n"
            "<!-- cove-guidance end -->\n"
        )
        detail = tmp_path / ".agents" / "agents-md-detail" / "cove.md"
        detail.parent.mkdir(parents=True)
        detail.write_text("full guidance content")
        override = tmp_path / ".agents" / "cove" / "agents-md" / "cove.md"
        override.parent.mkdir(parents=True)
        override.write_text("project-level override")

        with patch("cove.cli.Path.home", return_value=tmp_path), patch(
            "subprocess.run"
        ) as mock_run, patch("shutil.rmtree"), patch.object(cove.cli.Path, "cwd", return_value=tmp_path):
            mock_run.return_value.returncode = 0

            _invoke_callback("uninstall", all_=True, force=True, global_=False)

        remaining = agents_md.read_text()
        assert "cove-guidance" not in remaining
        assert "# My Project" in remaining
        assert not detail.exists(), "detail cove.md should be removed during uninstall"
        assert not override.exists(), "project override should be removed during uninstall"

    def test_full_roundtrip_progressive_disclosure(self, tmp_path):
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")

        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text("# Existing Project\n")
        detail = tmp_path / ".agents" / "agents-md-detail" / "cove.md"
        override = tmp_path / ".agents" / "cove" / "agents-md" / "cove.md"

        with patch("cove.cli._container_env") as mock_env, patch.object(
            cove.cli.Path, "cwd", return_value=tmp_path
        ):
            mock_env.side_effect = [
                {"FORGEJO__server__ROOT_URL": "https://example.com:3000/",
                 "FORGEJO__server__DOMAIN": "example.com",
                 "FORGEJO__server__SSH_DOMAIN": "example.com",
                 "FORGEJO__server__SSH_PORT": "2222"},
                {"VAULT_ADDR": "http://127.0.0.1:8200"},
            ]

            runner = CliRunner()
            result = runner.invoke(cove.cli.app, ["install"])
            assert result.exit_code == 0

        assert detail.exists()
        detail_text = detail.read_text()
        assert "example.com" in detail_text

        assert override.exists()
        override_text = override.read_text()
        assert "example.com" in override_text
        assert "project-level override" in override_text
        assert "origin" in override_text
        assert "fj" in override_text

        agents_text = agents_md.read_text()
        assert "agents-md-detail/cove.md" in agents_text
        assert "Forgejo" in agents_text
        assert "Vault" in agents_text
        assert "Project override" in agents_text
        assert "# Existing Project" in agents_text


class TestUpRestartsStaleBinds:
    """Regression (2026-10-19 sev-2): `cove up` re-extracts bundled compose
    resources. Extraction used to prune-and-recopy every bind-mounted file,
    giving each a NEW inode even when its bytes were unchanged, and a running
    container kept the old (deleted) inode (e.g. /landing.html 404s). `cove up`
    must restart exactly the running containers that bind a file whose content
    actually changed — never the whole stack, never an untouched container."""

    @pytest.fixture(autouse=True)
    def _isolate_installed_resources(self, isolated_compose_resources):
        return isolated_compose_resources

    def _run_up_with(
        self, tmp_path, restarts, *, bundle_current, changed=(), unseals=None,
        vault_states=None, health=None, probes=None, sleeps=None,
        unseal_error=None,
    ):
        """Extended scaffolding for the compose-recreate heal tests:

        - vault_states: list of (container Id, State.StartedAt) tuples
          answered by the runtime-state `docker inspect`, consumed one per
          call (last reused). A None entry models an unreadable state (docker
          down / container absent). None (default) models unreadable always.
        - health: value returned by `cove.cli.vault_health` (default: Vault
          reachable, initialized, sealed), an Exception to raise per call, or
          a list consumed one entry per probe (last entry reused) — use the
          list form to model a Vault that answers its health endpoint only
          after a few retries.
        - probes / sleeps: recorder lists for vault_health calls and
          time.sleep backoffs; pass a list to assert on it.
        - unseal_error: exception raised by the patched ensure_unsealed."""
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")
        (compose_sub / "bringup.yml").write_text("---\n")

        home = tmp_path / "home"
        compose_dir = home / ".config" / "cove" / "compose"
        data_root = home / "Documents" / "cove-data"

        def _fake_run(cmd, *a, **k):
            class _R:
                returncode = 0
                stderr = ""
                stdout = ""
            r = _R()
            if cmd[:2] == ["docker", "ps"]:
                r.stdout = "cove-nginx\ncove-vault\ncove-dnsmasq\ncove-forgejo\n"
            elif cmd[:2] == ["docker", "inspect"] and "{{.Id}}" in cmd[-1]:
                # Runtime-state snapshot (Id + StartedAt) of cove-vault.
                if vault_states:
                    state = (
                        vault_states.pop(0)
                        if len(vault_states) > 1 else vault_states[0]
                    )
                else:
                    state = None
                if state is None:
                    r.returncode = 1
                    r.stderr = "Error: No such object: cove-vault"
                else:
                    r.stdout = f"{state[0]} {state[1]}\n"
            elif cmd[:2] == ["docker", "inspect"]:
                mounts = {
                    "cove-nginx": [
                        compose_dir / "nginx" / "landing.html",
                        data_root / "nginx" / "config.html",
                    ],
                    "cove-vault": [compose_dir / "vault" / "vault.hcl"],
                    "cove-dnsmasq": [data_root / "dnsmasq" / "cove.conf"],
                    "cove-forgejo": [data_root / "forgejo" / "gitea"],
                }[cmd[2]]
                r.stdout = "".join(f"{m}\n" for m in mounts)
            elif cmd[:2] == ["docker", "restart"]:
                restarts.append(list(cmd))
            return r

        def _fake_unseal():
            if unseal_error is not None:
                raise unseal_error
            if unseals is not None:
                unseals.append(True)
            return {"sealed": False}

        def _fake_health(*args, **kwargs):
            # The heal's bounded health probe. Default: Vault reachable,
            # initialized and sealed, so a triggered heal proceeds to
            # ensure_unsealed (which the unseals list observes). A list is
            # consumed one entry per probe (last reused) to model a Vault
            # that answers only after some retries.
            value = health
            if isinstance(value, list):
                value = value.pop(0) if len(value) > 1 else value[0]
            if probes is not None:
                probes.append(value)
            if isinstance(value, Exception):
                raise value
            return {"initialized": True, "sealed": True} if value is None else value

        _sleep_recorder = sleeps if sleeps is not None else []

        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path), patch.object(
            cove.cli.Path, "home", classmethod(lambda cls: home)
        ), patch("cove.cli.subprocess.run", side_effect=_fake_run), patch(
            "cove.cli.ensure_host_vars", return_value=tmp_path / "nonexistent.yml"
        ), patch("cove.cli.bundle_is_current", return_value=bundle_current), patch(
            "cove.cli.changed_resource_files", return_value=frozenset(changed)
        ), patch("cove.cli.ensure_unsealed", side_effect=_fake_unseal), patch(
            "cove.cli.vault_health", side_effect=_fake_health
        ), patch("cove.cli.time.sleep", side_effect=lambda s: _sleep_recorder.append(s)), patch(
            "cove.status.check_all", return_value=[]
        ), patch("cove.cli._detect_running_optional_profiles", return_value=[]), patch(
            "cove.cli.getpass.getpass", return_value="secret"
        ):
            _invoke_callback(
                "up", no_provision=True, no_upgrade=False, all_=False, log=False
            )

    def test_restarts_only_containers_binding_changed_files(
        self, tmp_path, _fake_ansible_popen
    ):
        restarts: list = []
        self._run_up_with(
            tmp_path,
            restarts,
            bundle_current=False,
            changed={"nginx/landing.html", "vault/vault.hcl"},
        )
        restarted = {c[2] for c in restarts}
        assert restarted == {"cove-nginx", "cove-vault"}, (
            "only running containers whose bind sources changed must be "
            f"restarted, got: {restarts}"
        )

    def test_no_restart_when_bundle_already_current(
        self, tmp_path, _fake_ansible_popen
    ):
        restarts: list = []
        self._run_up_with(tmp_path, restarts, bundle_current=True)
        assert restarts == [], (
            "the deployed bundle already matched, so extraction did not run and "
            "no container's bind inode changed"
        )

    def test_unchanged_bundle_file_does_not_restart_its_container(
        self, tmp_path, _fake_ansible_popen
    ):
        """The root fix: extraction preserves the inode of content-identical
        files, so only files in `changed_resource_files()` can trigger a
        restart. `vault/vault.hcl` unchanged ⇒ Vault is left alone."""
        restarts: list = []
        self._run_up_with(
            tmp_path,
            restarts,
            bundle_current=False,
            changed={"nginx/landing.html"},
        )
        restarted = {c[2] for c in restarts}
        assert restarted == {"cove-nginx"}, (
            "a container whose bound file content is unchanged must not be "
            f"restarted, got: {restarts}"
        )


class TestUpHealsSealedVault:
    """A genuine `vault/vault.hcl` change must restart Vault (its config is read
    only at startup), and Vault then comes up SEALED. `cove up` must heal that
    from the keystore on every run: `cove update` converges via
    `cove up --no-provision`, which skips `bootstrap_vault.yml`, so gating the
    heal on "provisioning enabled" would leave an updated machine sealed."""

    @pytest.fixture(autouse=True)
    def _isolate_installed_resources(self, isolated_compose_resources):
        return isolated_compose_resources

    def _up(self, tmp_path, unseals, *, changed, bundle_current=False):
        TestUpRestartsStaleBinds()._run_up_with(
            tmp_path,
            [],
            bundle_current=bundle_current,
            changed=changed,
            unseals=unseals,
        )

    def test_unseals_vault_after_restarting_it(self, tmp_path, _fake_ansible_popen):
        unseals: list = []
        self._up(tmp_path, unseals, changed={"vault/vault.hcl"})
        assert unseals == [True], (
            "a restarted Vault comes up sealed; cove up must unseal it from the "
            "keystore"
        )

    def test_unseals_vault_even_when_provisioning_is_skipped(
        self, tmp_path, _fake_ansible_popen
    ):
        """`cove update` converges with `--no-provision`; the heal must not
        depend on bootstrap_vault.yml running."""
        unseals: list = []
        self._up(tmp_path, unseals, changed={"vault/vault.hcl"})
        playbooks = [str(p) for call in _fake_ansible_popen["calls"] for p in call]
        assert not any("bootstrap_vault.yml" in p for p in playbooks), (
            "precondition: no-provision skips bootstrap_vault.yml, so the "
            "unseal below cannot have come from it"
        )
        assert len(unseals) == 1

    def test_no_unseal_attempt_when_vault_was_not_restarted(
        self, tmp_path, _fake_ansible_popen
    ):
        unseals: list = []
        self._up(tmp_path, unseals, changed={"nginx/landing.html"})
        assert unseals == [], (
            "an untouched Vault must not be probed or unsealed"
        )


class TestUpHealsVaultRecreatedByCompose:
    """Regression (two live occurrences): the PR #75 heal only covers a Vault
    the CLI itself restarted (stale changed-file bind). When the compose run
    itself recreates `cove-vault` — a rotated credential in the compose .env,
    a bundle-driven service re-render, a bringup handler restart — `cove up`
    used to complete and leave Vault SEALED:

    - 2026-10-20 22:23Z: `cove up --no-provision` converge recreated
      cove-vault; status read 'Vault API: sealed' right after up.
    - 2026-10-21 14:58Z: operator `cove up` (rotated credential) recreated
      cove-vault; it stayed sealed, unnoticed, for hours.

    Detection: a runtime snapshot (container Id + State.StartedAt) taken
    before the bringup compose run and compared after it. A changed Id is a
    compose recreate; a changed StartedAt on the same Id is a restart (docker
    restart keeps the Id) — covering bringup handlers too. An untouched Vault
    is never probed, not even with a health GET."""

    @pytest.fixture(autouse=True)
    def _isolate_installed_resources(self, isolated_compose_resources):
        return isolated_compose_resources

    def _up(self, tmp_path, **kwargs):
        restarts: list = []
        TestUpRestartsStaleBinds()._run_up_with(
            tmp_path, restarts,
            bundle_current=kwargs.pop("bundle_current", True),
            **kwargs
        )
        return restarts

    def test_unseals_vault_recreated_by_compose(self, tmp_path, _fake_ansible_popen):
        """THE failing case before the fix: nothing changed in the bundle and
        no CLI restart ran — the compose invocation itself recreated
        cove-vault. `cove up` must still unseal it, exactly once."""
        unseals, probes = [], []
        restarts = self._up(
            tmp_path,
            unseals=unseals,
            probes=probes,
            vault_states=[
                ("id-before", "2026-10-21T10:00:00Z"),
                ("id-after", "2026-10-21T14:58:06Z"),
            ],
        )
        assert restarts == [], (
            "precondition: no CLI restart ran; the recreate came from the "
            f"compose invocation itself, got {restarts}"
        )
        assert len(probes) == 1, f"exactly one health probe, got {probes}"
        assert unseals == [True], (
            "a compose-recreated Vault comes up sealed; cove up must unseal "
            f"it from the keystore, got {unseals}"
        )

    def test_unseals_vault_restarted_in_place_by_bringup_handler(
        self, tmp_path, _fake_ansible_popen
    ):
        """A bringup-handler restart keeps the container Id but bumps
        State.StartedAt — still a (re)start this `up` caused, still sealed."""
        unseals, probes = [], []
        self._up(
            tmp_path,
            unseals=unseals,
            probes=probes,
            vault_states=[
                ("id-same", "2026-10-21T10:00:00Z"),
                ("id-same", "2026-10-21T14:58:06Z"),
            ],
        )
        assert len(probes) == 1, f"exactly one health probe, got {probes}"
        assert unseals == [True], (
            "a bringup-handler-restarted Vault comes up sealed and must be "
            f"unsealed, got {unseals}"
        )

    def test_untouched_vault_is_never_probed(self, tmp_path, _fake_ansible_popen):
        """The PR #75 negative property, strengthened for the compose path:
        when nothing (re)started Vault — not the CLI restart list, not the
        snapshot — `cove up` must not so much as health-probe it."""
        unseals, probes, sleeps = [], [], []
        restarts = self._up(
            tmp_path,
            bundle_current=False,
            changed={"nginx/landing.html"},
            unseals=unseals,
            probes=probes,
            sleeps=sleeps,
            vault_states=[
                ("id-stable", "2026-10-21T10:00:00Z"),
                ("id-stable", "2026-10-21T10:00:00Z"),
            ],
        )
        assert {c[2] for c in restarts} == {"cove-nginx"}, (
            "precondition: only the nginx stale bind restarted; Vault "
            f"untouched, got {restarts}"
        )
        assert probes == [], "an untouched Vault must not be probed"
        assert unseals == [], "an untouched Vault must not be unsealed"
        assert sleeps == [], "no retry backoff may run when Vault was untouched"

    def test_vault_absent_before_up_is_healed_when_compose_starts_it(
        self, tmp_path, _fake_ansible_popen
    ):
        """Stack was down (or the host rebooted): the container is absent in
        the pre-up snapshot and running after — this `up` started it, so a
        sealed initialized Vault must be healed."""
        unseals, probes = [], []
        self._up(
            tmp_path,
            unseals=unseals,
            probes=probes,
            vault_states=[
                None,
                ("id-new", "2026-10-21T14:58:06Z"),
            ],
        )
        assert len(probes) == 1, f"exactly one health probe, got {probes}"
        assert unseals == [True], (
            "a Vault started by this up comes up sealed and must be unsealed, "
            f"got {unseals}"
        )

    def test_uninitialized_vault_is_left_to_bootstrap(
        self, tmp_path, _fake_ansible_popen, capsys
    ):
        """First boot: the container is brand new and Vault is not
        initialized. ensure_unsealed would fail with 'not initialized' — the
        heal must skip it (bootstrap_vault.yml owns init+unseal) and, on
        --no-provision, warn that bootstrap was skipped."""
        unseals, probes = [], []
        self._up(
            tmp_path,
            unseals=unseals,
            probes=probes,
            health={"initialized": False, "sealed": True},
            vault_states=[None, ("id-new", "2026-10-21T14:58:06Z")],
        )
        assert len(probes) == 1, f"exactly one health probe, got {probes}"
        assert unseals == [], (
            "an uninitialized Vault must not be unsealed; bootstrap_vault.yml "
            "initializes it"
        )
        assert "not initialized" in capsys.readouterr().err

    def test_unreachable_vault_warns_and_is_left_to_the_status_gate(
        self, tmp_path, _fake_ansible_popen, capsys
    ):
        """A recreated Vault that never answers its health endpoint must not
        hang `up` (bounded retries, no unseal attempt, no keystore reads) and
        must not pass silently: a clear warning is printed and the end-of-up
        status gate reports Vault API failed (sealed/unreachable = ok=False,
        so `up` still exits 1)."""
        unseals, sleeps = [], []
        self._up(
            tmp_path,
            unseals=unseals,
            sleeps=sleeps,
            health=RuntimeError("Vault unreachable at https://vault.cove.local/"),
            vault_states=[
                ("id-before", "2026-10-21T10:00:00Z"),
                ("id-after", "2026-10-21T14:58:06Z"),
            ],
        )
        assert unseals == [], (
            "no unseal (and so no keystore read) may be attempted while Vault "
            f"is unreachable, got {unseals}"
        )
        assert len(sleeps) == cove.cli._VAULT_HEALTH_ATTEMPTS - 1, (
            f"retries must be bounded (attempt count minus one backoffs), "
            f"got {len(sleeps)}"
        )
        assert "may still be sealed" in capsys.readouterr().err

    def test_late_health_inside_the_window_still_unseals(
        self, tmp_path, _fake_ansible_popen
    ):
        """A recreated Vault that is slow to answer — health fails a few times
        then succeeds — must still be healed, not warned about. The window must
        swallow a normal Vault boot (2026-10-22: a 5x1.0s probe expired first
        and reported 'may still be sealed' on a Vault that was still starting).
        The loop returns the moment Vault answers, so the probe count is
        exactly the failures plus one success."""
        unseals, probes, sleeps = [], [], []
        self._up(
            tmp_path,
            unseals=unseals,
            probes=probes,
            sleeps=sleeps,
            health=[
                RuntimeError("Vault unreachable at https://vault.cove.local/"),
                RuntimeError("Vault unreachable at https://vault.cove.local/"),
                {"initialized": True, "sealed": True},
            ],
            vault_states=[
                ("id-before", "2026-10-21T10:00:00Z"),
                ("id-after", "2026-10-21T14:58:06Z"),
            ],
        )
        assert len(probes) == 3, (
            "the probe must retry until Vault answers, then stop immediately, "
            f"got {probes}"
        )
        assert len(sleeps) == 2, (
            f"one backoff between each probe pair, got {len(sleeps)}"
        )
        assert unseals == [True], (
            "a Vault that answers inside the bounded window comes up sealed "
            f"and must be unsealed, got {unseals}"
        )

    def test_health_probe_window_covers_a_normal_vault_boot(self):
        """Regression guard for the window width: the nominal coverage
        (attempts x retry interval) must span at least 30s so a freshly
        recreated Vault has time to answer, while the loop stays bounded."""
        coverage = (
            cove.cli._VAULT_HEALTH_ATTEMPTS * cove.cli._VAULT_HEALTH_RETRY_SECONDS
        )
        assert coverage >= 30.0, (
            "the bounded Vault heal probe must cover a normal Vault boot "
            f"(>=30s), got {coverage}s"
        )

    def test_unseal_failure_warns_and_is_non_fatal(
        self, tmp_path, _fake_ansible_popen, capsys
    ):
        """Operator decision 2026-10-22 (amends PR #79/#83 fail-loud): a heal
        that ran but could not unseal no longer aborts `up` with a
        ClickException. It prints a warning naming `cove vault unseal` and
        continues; the end-of-up status gate (patched empty here) is what
        reports a still-sealed Vault."""
        unseals: list = []
        self._up(
            tmp_path,
            unseals=unseals,
            unseal_error=RuntimeError(
                "Keystore read failed for cove/vault/unseal-1"
            ),
            vault_states=[
                ("id-before", "2026-10-21T10:00:00Z"),
                ("id-after", "2026-10-21T14:58:06Z"),
            ],
        )
        err = capsys.readouterr().err
        assert "could not be unsealed automatically" in err, (
            f"a failed unseal must warn, got stderr: {err!r}"
        )
        assert "cove vault unseal" in err

    def test_compose_recreate_and_cli_restart_heal_exactly_once(
        self, tmp_path, _fake_ansible_popen
    ):
        """When both detectors fire (compose recreated the container AND a
        changed vault.hcl triggered the CLI stale-bind restart), the heal
        must run once, not twice."""
        unseals, probes = [], []
        restarts: list = []
        TestUpRestartsStaleBinds()._run_up_with(
            tmp_path,
            restarts,
            bundle_current=False,
            changed={"vault/vault.hcl"},
            unseals=unseals,
            probes=probes,
            vault_states=[
                ("id-before", "2026-10-21T10:00:00Z"),
                ("id-after", "2026-10-21T14:58:06Z"),
            ],
        )
        assert "cove-vault" in {c[2] for c in restarts}, (
            f"precondition: the CLI stale-bind restart ran, got {restarts}"
        )
        assert len(unseals) == 1 and len(probes) == 1, (
            f"both detectors firing must heal exactly once: "
            f"unseals={unseals}, probes={probes}"
        )


class TestNoUpgradeFlag:
    @pytest.fixture(autouse=True)
    def _isolate_installed_resources(self, isolated_compose_resources):
        return isolated_compose_resources

    def test_no_upgrade_skips_reextract(self, tmp_path, monkeypatch):
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")
        (compose_sub / "bringup.yml").write_text("---\n")
        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path), patch(
            "subprocess.run"
        ) as mock_run, patch(
            "cove.cli.ensure_host_vars", return_value=tmp_path / "nonexistent.yml"
        ), patch("cove.cli.maybe_reextract") as mock_reextract, patch("cove.status.check_all") as mock_check, patch(
            "cove.cli._detect_running_optional_profiles", return_value=[]
        ), patch("cove.cli.getpass.getpass", return_value="secret"):
            mock_run.return_value.returncode = 0
            mock_check.return_value = []
            _invoke_callback("up", all_=False,
                no_provision=True, no_upgrade=True, log=False
            )
            mock_reextract.assert_not_called()


class TestInitPurge:
    def test_init_purge_removes_compose_dir(self, tmp_path, monkeypatch):
        compose_dir = tmp_path / ".config" / "cove" / "compose"
        compose_dir.mkdir(parents=True)
        (compose_dir / ".version").write_text("0.1.0")
        (compose_dir / "inventory.yml").write_text("---\n")
        with patch("cove.cli.Path.home", return_value=tmp_path):
            runner = CliRunner()
            result = runner.invoke(cove.cli.app, ["init", "--purge"])
            assert result.exit_code == 0
            assert not compose_dir.exists()

    def test_init_purge_when_absent(self, tmp_path, monkeypatch):
        with patch("cove.cli.Path.home", return_value=tmp_path):
            runner = CliRunner()
            result = runner.invoke(cove.cli.app, ["init", "--purge"])
            assert result.exit_code == 0
            assert "Nothing to remove" in result.output
    def test_ade_probes_nginx_https_port(self):
        """cove ade's health probes must use constants.NGINX_HTTPS_PORT — the
        pf shim is gone, nginx owns 443, and nothing listens on 8443. The
        ade-update-command branch predates the pf drop and shipped a dead
        ADE_HEALTH_PORT = 8443: `cove ade status` reported UNREACHABLE on healthy
        machines and `cove ade update`'s health-wait would spuriously fail and
        roll back."""
        text = (CLI_DIR / "cove" / "ade.py").read_text()
        assert "8443" not in text, (
            "ade.py must not hardcode the dead 8443 HTTPS port (nginx owns 443)"
        )
        assert "NGINX_HTTPS_PORT" in text, (
            "ade.py must use the single source of truth NGINX_HTTPS_PORT"
        )
