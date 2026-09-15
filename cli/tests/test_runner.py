"""Tests for Forgejo Actions Runner: compose config, CLI module,
bringup greps, provision greps, and resource sync integrity.

Per the plan (`docs/plans/forgejo-actions-runner.md`), the runner is an optional
profiled Cove service (`profile: runner`) that polls Forgejo for Actions
workflows. It mirrors the litellm/speedtest pattern for optional services.

Run all:   pytest cli/tests/test_runner.py
Run unit:  pytest cli/tests/test_runner.py -m "not e2e and not staging"
"""

from pathlib import Path

import pytest
import yaml


def _project_root() -> Path:
    start = Path(__file__).resolve().parent
    for _ in range(6):
        if (start / "compose" / "inventory.yml").exists():
            return start
        start = start.parent
    raise RuntimeError(f"Cannot find project root from {__file__}")


PROJECT_ROOT = _project_root()
COMPOSE_DIR = PROJECT_ROOT / "compose"
RESOURCES_COMPOSE_DIR = (
    PROJECT_ROOT / "cli" / "cove" / "resources" / "compose"
)


def _load_compose() -> dict:
    with open(COMPOSE_DIR / "docker-compose.yml") as f:
        return yaml.safe_load(f)


def _load_bringup() -> dict:
    with open(COMPOSE_DIR / "bringup.yml") as f:
        return yaml.safe_load(f)


def _load_provision() -> str:
    with open(COMPOSE_DIR / "provision_forgejo.yml") as f:
        return f.read()


class TestComposeServiceDefinition:
    """Validate the forgejo-runner service definition in docker-compose.yml."""

    def test_runner_service_exists(self):
        data = _load_compose()
        assert "forgejo-runner" in data["services"], (
            "forgejo-runner service missing from compose"
        )

    def test_runner_has_profile(self):
        data = _load_compose()
        profiles = data["services"]["forgejo-runner"].get("profiles", [])
        assert "runner" in profiles, (
            "forgejo-runner service must have profiles: [\"runner\"]"
        )

    def test_runner_has_no_ports(self):
        data = _load_compose()
        ports = data["services"]["forgejo-runner"].get("ports", [])
        assert ports is None or ports == [], (
            "forgejo-runner must have no exposed ports (outbound-only)"
        )

    def test_runner_has_memory_limit(self):
        data = _load_compose()
        deploy = data["services"]["forgejo-runner"].get("deploy", {})
        limits = deploy.get("resources", {}).get("limits", {})
        assert "memory" in limits, "forgejo-runner must have a memory limit"

    def test_runner_image_pinned(self):
        data = _load_compose()
        image = str(data["services"]["forgejo-runner"].get("image", ""))
        assert ":latest" not in image, (
            f"forgejo-runner image must be version-pinned, got: {image}"
        )
        assert ":" in image, (
            f"forgejo-runner image must have a version tag, got: {image}"
        )

    def test_runner_docker_socket_mount(self):
        data = _load_compose()
        volumes = data["services"]["forgejo-runner"].get("volumes", [])
        volume_strs = [str(v) for v in volumes]
        assert any("/var/run/docker.sock" in v for v in volume_strs), (
            "forgejo-runner must mount the Docker socket for job containers"
        )

    def test_runner_data_volume_from_data_root(self):
        data = _load_compose()
        volumes = data["services"]["forgejo-runner"].get("volumes", [])
        volume_strs = [str(v) for v in volumes]
        assert any("forgejo-runner" in v and "/data" in v for v in volume_strs), (
            "forgejo-runner must mount data volume to /data under FORGEJO_RUNNER_DATA_ROOT"
        )

    def test_runner_container_name_cove_prefix(self):
        data = _load_compose()
        name = str(data["services"]["forgejo-runner"].get("container_name", ""))
        assert "cove-" in name, (
            f"container_name must default to cove- prefix, got: {name}"
        )

    def test_runner_restart_policy(self):
        data = _load_compose()
        restart = data["services"]["forgejo-runner"].get("restart", "")
        assert restart == "unless-stopped", (
            f"forgejo-runner must have restart: unless-stopped, got: {restart}"
        )

    def test_runner_docker_host_env(self):
        data = _load_compose()
        env = data["services"]["forgejo-runner"].get("environment", {})
        assert "DOCKER_HOST" in env, (
            "forgejo-runner must set DOCKER_HOST environment variable"
        )
        assert "unix:///var/run/docker.sock" in str(env.get("DOCKER_HOST", "")), (
            f"DOCKER_HOST must point to the mounted socket, got: {env.get('DOCKER_HOST')!r}"
        )


class TestCLI:
    """Validate the cove runner CLI module."""

    def test_runner_group_imports(self):
        from cove.runner import runner
        assert runner is not None

    def test_runner_group_registered(self):
        from cove.cli import app
        commands = list(app.commands.keys())
        assert "runner" in commands, "runner group must be registered in cli.py"

    def test_runner_has_up_command(self):
        from cove.runner import runner
        commands = list(runner.commands.keys())
        assert "up" in commands

    def test_runner_has_down_command(self):
        from cove.runner import runner
        commands = list(runner.commands.keys())
        assert "down" in commands

    def test_runner_has_status_command(self):
        from cove.runner import runner
        commands = list(runner.commands.keys())
        assert "status" in commands

    def test_runner_has_logs_command(self):
        from cove.runner import runner
        commands = list(runner.commands.keys())
        assert "logs" in commands

    def test_runner_up_uses_profile_flag(self):
        source = (PROJECT_ROOT / "cli" / "cove" / "runner.py").read_text()
        assert "--profile" in source and "runner" in source, (
            "cove runner up must use --profile runner"
        )

    def test_runner_up_profile_before_subcommand(self):
        """docker compose requires --profile as a GLOBAL flag BEFORE the
        subcommand. `cove runner up` must pass `--profile runner` before `up`."""
        from click.testing import CliRunner
        from cove.runner import runner
        from unittest.mock import patch
        from types import SimpleNamespace

        captured = []

        def fake_subprocess_run(cmd, **kwargs):
            captured.append(list(cmd))
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch("cove.runner.subprocess.run", side_effect=fake_subprocess_run):
            runner_obj = CliRunner()
            result = runner_obj.invoke(runner, ["up"])

        assert result.exit_code == 0, f"cove runner up failed: {result.output}"
        assert captured, "no subprocess call captured"
        compose_cmds = [c for c in captured if c and c[0] == "docker" and len(c) > 1 and c[1] == "compose"]
        assert compose_cmds, f"no docker compose call captured: {captured}"
        cmd = compose_cmds[0]
        up_idx = cmd.index("up")
        assert "--profile" in cmd, f"--profile missing from compose cmd: {cmd}"
        prof_idx = cmd.index("--profile")
        assert prof_idx < up_idx, (
            f"--profile must precede 'up' (global flag), got cmd: {cmd}"
        )

    def test_runner_down_uses_stop(self):
        """cove runner down must use 'stop' not 'down' to avoid stopping
        core Cove services."""
        source = (PROJECT_ROOT / "cli" / "cove" / "runner.py").read_text()
        assert '"stop"' in source or "'stop'" in source, (
            "cove runner down must use 'stop' command, not 'down'"
        )


class TestBringupIntegration:
    """Validate bringup.yml includes runner vars and data directory."""

    def test_bringup_env_includes_runner_vars(self):
        with open(COMPOSE_DIR / "bringup.yml") as f:
            content = f.read()
        assert "FORGEJO_RUNNER_IMAGE" in content, (
            "bringup.yml .env must include FORGEJO_RUNNER_IMAGE"
        )
        assert "FORGEJO_RUNNER_CONTAINER_NAME" in content, (
            "bringup.yml .env must include FORGEJO_RUNNER_CONTAINER_NAME"
        )
        assert "FORGEJO_RUNNER_DATA_ROOT" in content, (
            "bringup.yml .env must include FORGEJO_RUNNER_DATA_ROOT"
        )

    def test_bringup_creates_runner_data_dir(self):
        bringup = _load_bringup()
        tasks = bringup[0]["tasks"] if isinstance(bringup, list) else bringup.get("tasks", [])
        data_dir_tasks = [
            t for t in tasks
            if isinstance(t, dict) and "data" in (t.get("name", "") or "").lower()
        ]
        assert data_dir_tasks, "No data directory task found in bringup.yml"
        loop = data_dir_tasks[0].get("loop", [])
        assert any("forgejo-runner" in str(item) for item in loop), (
            "bringup.yml must create the forgejo-runner data directory"
        )

    def test_bringup_env_render_is_first_boot_only(self):
        """The compose .env render must be conditional (`when: not exists`) so
        a subsequent `cove up` does NOT clobber the FORGEJO_RUNNER vars."""
        bringup = _load_bringup()
        tasks = bringup[0]["tasks"] if isinstance(bringup, list) else bringup.get("tasks", [])
        env_tasks = [
            t for t in tasks
            if isinstance(t, dict)
            and "env" in (t.get("name", "") or "").lower()
            and "FORGEJO_RUNNER" in str(t.get("ansible.builtin.copy", {}).get("content", ""))
        ]
        assert env_tasks, "No .env render task with FORGEJO_RUNNER vars found in bringup.yml"
        for t in env_tasks:
            when = t.get("when", "")
            assert "is exists" in str(when) and "not" in str(when), (
                "compose .env render must be conditional `when: not (...) is exists` "
                f"(first boot only); got when={when!r}"
            )


class TestProvisionRunner:
    """Validate provision_forgejo.yml includes runner registration tasks."""

    def test_provision_fetches_registration_token(self):
        content = _load_provision()
        assert "registration-token" in content, (
            "provision_forgejo.yml must fetch the registration token from the Forgejo API"
        )

    def test_provision_registers_no_interactive(self):
        content = _load_provision()
        assert "--no-interactive" in content, (
            "provision_forgejo.yml must register the runner non-interactively"
        )

    def test_provision_skip_if_registered_idempotent(self):
        content = _load_provision()
        assert "runner_registration_check" in content, (
            "provision_forgejo.yml must check for existing registration (idempotent skip)"
        )

    def test_provision_runner_registers_with_forgejo_url(self):
        content = _load_provision()
        assert "http://forgejo:3000/" in content, (
            "provision_forgejo.yml must register the runner with http://forgejo:3000/"
        )


class TestStatusOptionalServices:
    """Validate status.py includes the runner as an optional service."""

    def test_runner_in_optional_services(self):
        from cove.status import OPTIONAL_SERVICES
        names = [label for _, label, _ in OPTIONAL_SERVICES]
        assert "Runner" in names, "Runner must be in OPTIONAL_SERVICES"

    def test_runner_not_in_required_services(self):
        from cove.status import SERVICES
        names = [name for _, name in SERVICES]
        assert "Runner" not in names, (
            "Runner must NOT be in required SERVICES — it's optional"
        )


class TestResourcesSync:
    """Validate the bundled compose resources reflect the compose/ source
    (integrity/drift guard). The resources dir is a build artifact synced via
    cli/scripts/sync_compose_resources.py."""

    def test_resources_tree_in_sync(self):
        if not RESOURCES_COMPOSE_DIR.is_dir():
            pytest.skip(
                "cli/cove/resources/compose/ missing — run "
                "python3 cli/scripts/sync_compose_resources.py"
            )
        excluded_names = {".env", "default.conf", "cove.conf"}
        for rel in [
            "docker-compose.yml",
            "bringup.yml",
            "provision_forgejo.yml",
        ]:
            src = COMPOSE_DIR / rel
            dst = RESOURCES_COMPOSE_DIR / rel
            if src.name in excluded_names:
                continue
            if not dst.exists():
                pytest.fail(
                    f"bundled resources missing {rel} — run sync_compose_resources.py"
                )
            assert src.read_bytes() == dst.read_bytes(), (
                f"bundled resources out of sync for {rel} — run sync_compose_resources.py"
            )


class TestAuthPosture:
    """Adversarial/security assertions for the runner."""

    def test_auth_posture_documented(self):
        doc = PROJECT_ROOT / "docs" / "services" / "forgejo-runner.md"
        assert doc.exists(), "docs/services/forgejo-runner.md must exist"
        content = doc.read_text().lower()
        assert "auth" in content, "docs/services/forgejo-runner.md must state the auth posture"
        assert "registration" in content, (
            "docs/services/forgejo-runner.md must document registration (IaC)"
        )

    def test_runner_has_no_nginx_route(self):
        """The runner must NOT have a nginx route (outbound-only service)."""
        nginx_dir = COMPOSE_DIR / "nginx"
        if (nginx_dir / "default.conf.j2").exists():
            content = (nginx_dir / "default.conf.j2").read_text()
            assert "forgejo-runner" not in content, (
                "forgejo-runner must NOT have a nginx route (outbound-only service)"
            )

    def test_runner_no_exposed_ports(self):
        """The runner must not expose any ports to the host."""
        data = _load_compose()
        ports = data["services"]["forgejo-runner"].get("ports")
        assert ports is None or ports == [], (
            f"forgejo-runner must have no exposed ports, got: {ports}"
        )