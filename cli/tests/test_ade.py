"""Tests for the ADE (bb server) optional profiled service.

Per the plan (`docs/plans/ade-harness-phase1.md`), the ADE is an optional
profiled Cove service (`profile: ade`) running the pinned `bb-app` server,
reachable at `ade.cove` through nginx. It mirrors the litellm/speedtest/runner
pattern for optional services.

Run all:   pytest cli/tests/test_ade.py
Run unit:  pytest cli/tests/test_ade.py -m "not e2e and not staging"
"""

import re
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import yaml
from click.testing import CliRunner
from jinja2 import Environment, FileSystemLoader, StrictUndefined


def _project_root() -> Path:
    start = Path(__file__).resolve().parent
    for _ in range(6):
        if (start / "compose" / "inventory.yml").exists():
            return start
        start = start.parent
    raise RuntimeError(f"Cannot find project root from {__file__}")


PROJECT_ROOT = _project_root()
COMPOSE_DIR = PROJECT_ROOT / "compose"
NGINX_DIR = COMPOSE_DIR / "nginx"
RESOURCES_COMPOSE_DIR = PROJECT_ROOT / "cli" / "cove" / "resources" / "compose"

TEMPLATE_VARS = {
    "ansible_hostname": "testhost",
    "ts_ip": "100.64.0.1",
    "ts_dns_name": "testhost.tailnet.ts.net",
    "ca_uuid": "00000000-0000-0000-0000-000000000001",
    "dns_uuid": "00000000-0000-0000-0000-000000000002",
    "profile_uuid": "00000000-0000-0000-0000-000000000003",
    "root_ca_b64": "dGVzdC1jYS1iNjQ=",
}


@pytest.fixture(autouse=True)
def _pin_compose_dir(monkeypatch):
    """Pin COVE_COMPOSE_DIR so CLI tests don't shell out to git to resolve it."""
    monkeypatch.setenv("COVE_COMPOSE_DIR", str(COMPOSE_DIR))


def _load_compose() -> dict:
    with open(COMPOSE_DIR / "docker-compose.yml") as f:
        return yaml.safe_load(f)


def _load_bringup() -> dict:
    with open(COMPOSE_DIR / "bringup.yml") as f:
        return yaml.safe_load(f)


def _load_group_vars() -> dict:
    with open(COMPOSE_DIR / "group_vars" / "all.yml") as f:
        return yaml.safe_load(f)


def _render_nginx(extra: dict | None = None) -> str:
    env = Environment(loader=FileSystemLoader(str(NGINX_DIR)), undefined=StrictUndefined)
    tmpl = env.get_template("default.conf.j2")
    return tmpl.render({**TEMPLATE_VARS, **(extra or {})})


def _ade_block(rendered: str) -> str:
    """Extract the ade.cove server block from the rendered nginx config."""
    lines = rendered.split("\n")
    start = None
    last_server = None
    for i, line in enumerate(lines):
        if line.strip().startswith("server {"):
            last_server = i
        if "server_name ade.cove" in line and last_server is not None:
            start = last_server
            break
    assert start is not None, "ade.cove server block not found in rendered nginx"
    depth = 0
    out = []
    for line in lines[start:]:
        depth += line.count("{") - line.count("}")
        out.append(line)
        if depth == 0:
            break
    return "\n".join(out)


class TestComposeServiceDefinition:
    """Validate the ade service definition in docker-compose.yml."""

    def test_ade_service_exists(self):
        data = _load_compose()
        assert "ade" in data["services"], "ade service missing from compose"

    def test_ade_has_profile(self):
        data = _load_compose()
        profiles = data["services"]["ade"].get("profiles", [])
        assert "ade" in profiles, 'ade service must have profiles: ["ade"]'

    def test_ade_has_build_context(self):
        data = _load_compose()
        build = data["services"]["ade"].get("build")
        assert build, "ade service must build from compose/ade"
        context = str(build.get("context", "")) if isinstance(build, dict) else str(build)
        assert "ade" in context, f"ade build context must point at compose/ade, got: {build}"

    def test_ade_pins_bb_app_version(self):
        data = _load_compose()
        build = data["services"]["ade"].get("build", {})
        args = build.get("args", {})
        assert "BB_APP_VERSION" in args, "ade build must pass BB_APP_VERSION"

    def test_ade_image_pinned(self):
        data = _load_compose()
        image = str(data["services"]["ade"].get("image", ""))
        assert ":latest" not in image, f"ade image must be pinned, got: {image}"
        assert ":" in image, f"ade image must have a version tag, got: {image}"

    def test_ade_container_name_cove_prefix(self):
        data = _load_compose()
        name = str(data["services"]["ade"].get("container_name", ""))
        assert "cove-" in name, f"container_name must default to cove- prefix, got: {name}"

    def test_ade_data_volume_uses_cove_data_root(self):
        data = _load_compose()
        volumes = [str(v) for v in data["services"]["ade"].get("volumes", [])]
        assert any("${COVE_DATA_ROOT" in v and "ade" in v for v in volumes), (
            f"ade must mount data under ${{COVE_DATA_ROOT}}/ade, got: {volumes}"
        )

    def test_ade_has_no_host_ports(self):
        data = _load_compose()
        ports = data["services"]["ade"].get("ports")
        assert ports is None or ports == [], (
            f"ade must expose no host ports (reached over the cove network), got: {ports}"
        )

    def test_ade_binds_wildcard_inside_container(self):
        data = _load_compose()
        env = data["services"]["ade"].get("environment", {})
        assert str(env.get("BB_SERVER_BIND_HOST", "")) == "0.0.0.0", (
            "ade must set BB_SERVER_BIND_HOST=0.0.0.0 so nginx reaches it"
        )

    def test_ade_port_is_threaded_from_ade_port(self):
        """ADE_PORT must be the single source of truth for the server port."""
        data = _load_compose()
        env = data["services"]["ade"].get("environment", {})
        assert str(env.get("BB_SERVER_PORT", "")) == "${ADE_PORT:-38886}", (
            f"compose BB_SERVER_PORT must thread ${{ADE_PORT}}, got: {env.get('BB_SERVER_PORT')!r}"
        )

    def test_ade_port_defined_in_group_vars(self):
        """nginx is rendered by bringup from the live Ansible var, not from the
        compose .env. `ade_port` must be defined once in group_vars/all.yml so
        the nginx upstream and the rendered .env line share one source."""
        group_vars = _load_group_vars()
        assert "ade_port" in group_vars, (
            "group_vars/all.yml must define ade_port (mirror nginx_https_port)"
        )
        assert str(group_vars["ade_port"]) == "38886", (
            f"ade_port default must be 38886, got: {group_vars['ade_port']!r}"
        )
        assert "ade_container_name" in group_vars, (
            "group_vars/all.yml must define ade_container_name"
        )

    def test_nginx_upstream_and_env_share_ade_port_var(self):
        """The nginx template and bringup's .env line must both derive from the
        same Ansible var `ade_port`, so changing it once reconciles both."""
        nginx = (NGINX_DIR / "default.conf.j2").read_text()
        bringup = (COMPOSE_DIR / "bringup.yml").read_text()
        assert "ade_port" in nginx, "nginx template must reference ade_port"
        assert re.search(r"^\s*ADE_PORT=\{\{ ade_port", bringup, re.MULTILINE), (
            "bringup .env must set ADE_PORT from the same ade_port var"
        )

    def test_ade_healthcheck_port_is_threaded(self):
        data = _load_compose()
        hc = data["services"]["ade"].get("healthcheck", {})
        test = " ".join(str(t) for t in hc.get("test", []))
        assert "${ADE_PORT:-38886}" in test, (
            f"healthcheck must thread ${{ADE_PORT}}, got: {test!r}"
        )

    def test_ade_dockerfile_does_not_hardcode_port(self):
        """The Dockerfile must not pin --server-port/--server-bind-host in CMD
        (explicit flags override env); port comes from BB_SERVER_PORT env."""
        content = (COMPOSE_DIR / "ade" / "Dockerfile").read_text()
        assert "--server-port" not in content, (
            "Dockerfile must not hardcode --server-port (thread BB_SERVER_PORT instead)"
        )
        assert "--server-bind-host" not in content, (
            "Dockerfile must not hardcode --server-bind-host (thread BB_SERVER_BIND_HOST instead)"
        )
        assert "BB_SERVER_PORT" in content, "Dockerfile must default BB_SERVER_PORT"

    def test_ade_has_healthcheck(self):
        data = _load_compose()
        assert data["services"]["ade"].get("healthcheck") is not None, (
            "ade must define a healthcheck"
        )

    def test_ade_restart_policy(self):
        data = _load_compose()
        restart = data["services"]["ade"].get("restart", "")
        assert restart == "unless-stopped", f"ade restart must be unless-stopped, got: {restart}"


class TestCLI:
    """Validate the cove ade CLI module."""

    def test_ade_group_imports(self):
        from cove.ade import ade
        assert ade is not None

    def test_ade_group_registered(self):
        from cove.cli import app
        assert "ade" in app.commands, "ade group must be registered in cli.py"

    def test_ade_has_commands(self):
        from cove.ade import ade
        assert set(ade.commands.keys()) == {"up", "down", "status", "logs"}, (
            f"ade must expose up/down/status/logs, got: {list(ade.commands.keys())}"
        )

    def test_ade_up_uses_profile_flag_before_subcommand(self):
        from cove.ade import ade

        captured = []

        def fake_run(cmd, **kwargs):
            captured.append(list(cmd))
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch("cove.ade.subprocess.run", side_effect=fake_run):
            result = CliRunner().invoke(ade, ["up"])

        assert result.exit_code == 0, f"cove ade up failed: {result.output}"
        compose = [c for c in captured if c[:2] == ["docker", "compose"]]
        assert compose, f"no docker compose call captured: {captured}"
        cmd = compose[0]
        assert "--profile" in cmd and cmd.index("--profile") < cmd.index("up"), (
            f"--profile must precede 'up' (global flag), got: {cmd}"
        )

    def test_ade_down_uses_stop(self):
        from cove.ade import ade

        captured = []

        def fake_run(cmd, **kwargs):
            captured.append(list(cmd))
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch("cove.ade.subprocess.run", side_effect=fake_run):
            result = CliRunner().invoke(ade, ["down"])

        assert result.exit_code == 0, f"cove ade down failed: {result.output}"
        compose = [c for c in captured if c[:2] == ["docker", "compose"]]
        assert compose and "stop" in compose[0], (
            f"cove ade down must use 'stop', got: {compose}"
        )

    def test_ade_logs_targets_service(self):
        from cove.ade import ade

        captured = []

        def fake_run(cmd, **kwargs):
            captured.append(list(cmd))
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch("cove.ade.subprocess.run", side_effect=fake_run):
            result = CliRunner().invoke(ade, ["logs"])

        assert result.exit_code == 0, f"cove ade logs failed: {result.output}"
        compose = [c for c in captured if c[:2] == ["docker", "compose"]]
        assert compose and "ade" in compose[0], (
            f"logs must target the ade service, got: {compose}"
        )


class TestUpFailureModes:
    """`cove ade up` must fail loud and cleanly, not traceback."""

    def test_up_fails_loud_when_docker_missing(self):
        from cove.ade import ade

        with patch("cove.ade.subprocess.run", side_effect=FileNotFoundError("docker")):
            result = CliRunner().invoke(ade, ["up"])

        assert result.exit_code != 0, "up must exit non-zero when docker is absent"
        assert "docker" in result.output.lower(), (
            f"up must name the missing docker binary, got: {result.output}"
        )
        assert isinstance(result.exception, SystemExit), (
            "up must raise SystemExit, not leak a traceback"
        )

    def test_up_fails_loud_when_compose_fails(self):
        from cove.ade import ade

        err = subprocess.CalledProcessError(1, ["docker", "compose", "up"])
        with patch("cove.ade.subprocess.run", side_effect=err):
            result = CliRunner().invoke(ade, ["up"])

        assert result.exit_code != 0, "up must exit non-zero when compose fails"
        assert "failed" in result.output.lower() or "error" in result.output.lower(), (
            f"up must report the failure, got: {result.output}"
        )
        assert isinstance(result.exception, SystemExit), (
            "up must raise SystemExit, not leak a traceback"
        )


class TestDownFailureModes:
    """`cove ade down` must fail loud and cleanly, not traceback."""

    def test_down_fails_loud_when_docker_missing(self):
        from cove.ade import ade

        with patch("cove.ade.subprocess.run", side_effect=FileNotFoundError("docker")):
            result = CliRunner().invoke(ade, ["down"])

        assert result.exit_code != 0, "down must exit non-zero when docker is absent"
        assert "docker" in result.output.lower(), (
            f"down must name the missing docker binary, got: {result.output}"
        )
        assert isinstance(result.exception, SystemExit), (
            "down must raise SystemExit, not leak a traceback"
        )

    def test_down_fails_loud_when_compose_fails(self):
        from cove.ade import ade

        err = subprocess.CalledProcessError(1, ["docker", "compose", "stop", "ade"])
        with patch("cove.ade.subprocess.run", side_effect=err):
            result = CliRunner().invoke(ade, ["down"])

        assert result.exit_code != 0, "down must exit non-zero when compose fails"
        assert "failed" in result.output.lower() or "error" in result.output.lower(), (
            f"down must report the failure, got: {result.output}"
        )
        assert isinstance(result.exception, SystemExit), (
            "down must raise SystemExit, not leak a traceback"
        )
    """Failure-expecting tests: `cove ade status` must report unhealthy/absent
    and exit non-zero when the container is not running or upstream hangs."""

    def test_status_reports_absent_and_fails(self):
        from cove.ade import ade

        def fake_run(cmd, **kwargs):
            if cmd[:2] == ["docker", "compose"] and "ps" in cmd:
                return SimpleNamespace(
                    returncode=0, stdout="NAME\tSTATUS\tPORTS\n", stderr="",
                )
            return SimpleNamespace(returncode=1, stdout="", stderr="connection refused")

        with patch("cove.ade.subprocess.run", side_effect=fake_run):
            result = CliRunner().invoke(ade, ["status"])

        assert result.exit_code != 0, "status must exit non-zero when ade is down"
        assert "cove-ade-server" in result.output, (
            f"status must name the absent container, got: {result.output}"
        )
        assert "NOT RUNNING" in result.output or "UNREACHABLE" in result.output, (
            f"status must report unhealthy/absent, got: {result.output}"
        )

    def test_status_echoes_docker_stderr_on_ps_failure(self):
        from cove.ade import ade

        def fake_run(cmd, **kwargs):
            return SimpleNamespace(
                returncode=5,
                stdout="",
                stderr="Cannot connect to the Docker daemon at unix:///var/run/docker.sock",
            )

        with patch("cove.ade.subprocess.run", side_effect=fake_run):
            result = CliRunner().invoke(ade, ["status"])

        assert result.exit_code != 0, "status must exit non-zero on ps failure"
        assert "Cannot connect to the Docker daemon" in result.output, (
            f"status must echo docker stderr, got: {result.output}"
        )

    def test_status_reports_unreachable_on_timeout(self):
        from cove.ade import ade

        def fake_run(cmd, **kwargs):
            if cmd[:2] == ["docker", "compose"] and "ps" in cmd:
                return SimpleNamespace(
                    returncode=0,
                    stdout="NAME\tSTATUS\tPORTS\ncove-ade-server\tUp\t\n",
                    stderr="",
                )
            raise subprocess.TimeoutExpired(cmd, 10)

        with patch("cove.ade.subprocess.run", side_effect=fake_run):
            result = CliRunner().invoke(ade, ["status"])

        assert result.exit_code != 0, "status must exit non-zero when upstream hangs"
        assert "UNREACHABLE" in result.output, (
            f"status must report UNREACHABLE on timeout, got: {result.output}"
        )
        assert isinstance(result.exception, SystemExit), (
            "timeout must not leak a traceback; status must raise SystemExit"
        )

    def test_status_healthy_when_container_running(self):
        from cove.ade import ade

        def fake_run(cmd, **kwargs):
            if cmd[:2] == ["docker", "compose"] and "ps" in cmd:
                return SimpleNamespace(
                    returncode=0,
                    stdout="NAME\tSTATUS\tPORTS\ncove-ade-server\tUp 1 minute\t\n",
                    stderr="",
                )
            return SimpleNamespace(returncode=0, stdout='{"ok":true}', stderr="")

        with patch("cove.ade.subprocess.run", side_effect=fake_run):
            result = CliRunner().invoke(ade, ["status"])

        assert result.exit_code == 0, f"healthy status must exit 0: {result.output}"
        assert "Health: OK" in result.output, f"expected Health: OK, got: {result.output}"


class TestNginxConfig:
    """Validate nginx template renders the ade.cove server block."""

    def test_ade_server_block_exists(self):
        rendered = _render_nginx()
        assert "server_name ade.cove" in rendered
        assert "ade.cove.local" in rendered

    def test_ade_upstream_uses_stable_service_alias(self):
        """Target the compose service alias `ade`, not the overridable
        container_name (a container_name override would silently break nginx)."""
        rendered = _render_nginx()
        block = _ade_block(rendered)
        assert "http://ade:38886" in block, (
            f"ade upstream must use the service alias ade:38886, got:\n{block}"
        )
        assert "cove-ade-server" not in rendered, (
            "nginx must not target the overridable container_name"
        )

    def test_ade_upstream_port_is_threaded(self):
        rendered = _render_nginx({"ade_port": "39999"})
        assert "http://ade:39999" in rendered, (
            "ade upstream must thread ade_port"
        )

    def test_ade_uses_docker_resolver(self):
        rendered = _render_nginx()
        assert "resolver 127.0.0.11" in rendered

    def test_ade_location_restricts_access(self):
        """Unauthenticated command execution must not be reachable from the
        public internet: private ranges (LAN RFC1918, tailnet CGNAT 100.64/10,
        container ranges, loopback) allowed, all else denied. Operator decision
        2026-09-25 widened the list to LAN + tailnet."""
        rendered = _render_nginx()
        block = _ade_block(rendered)
        assert "allow 127.0.0.1;" in block, f"missing loopback allow:\n{block}"
        assert "allow ::1;" in block, f"missing IPv6 loopback allow:\n{block}"
        assert "allow 172.16.0.0/12;" in block, f"missing container-range allow:\n{block}"
        assert "allow 10.0.0.0/8;" in block, f"missing LAN 10/8 allow:\n{block}"
        assert "allow 192.168.0.0/16;" in block, f"missing LAN 192.168/16 allow:\n{block}"
        assert "allow 100.64.0.0/10;" in block, f"missing tailnet CGNAT allow:\n{block}"
        assert "deny all;" in block, f"missing deny all:\n{block}"

    def test_ade_websocket_upgrade_headers(self):
        rendered = _render_nginx()
        assert "map $http_upgrade $connection_upgrade" in rendered
        assert "proxy_http_version 1.1" in rendered
        assert "proxy_set_header Upgrade $http_upgrade" in rendered
        assert "proxy_set_header Connection $connection_upgrade" in rendered

    def test_ade_proxy_buffering_off(self):
        rendered = _render_nginx()
        assert "proxy_buffering off" in rendered


class TestBringupIntegration:
    """Validate bringup.yml wires ade vars, cert SANs, hosts, and data dir."""

    def test_bringup_env_includes_ade_vars(self):
        content = (COMPOSE_DIR / "bringup.yml").read_text()
        for key in ("ADE_IMAGE", "ADE_CONTAINER_NAME", "ADE_BB_APP_VERSION", "ADE_PORT"):
            assert key in content, f"bringup.yml .env must include {key}"

    def test_ade_image_tag_derives_from_pinned_version(self):
        """ADE_IMAGE must derive its tag from ADE_BB_APP_VERSION so the image
        tag cannot drift from the pinned bb-app version."""
        content = (COMPOSE_DIR / "bringup.yml").read_text()
        match = re.search(r"^\s*ADE_IMAGE=(.+)$", content, re.MULTILINE)
        assert match, "ADE_IMAGE line not found in bringup.yml"
        assert "ade_bb_app_version" in match.group(1), (
            f"ADE_IMAGE must derive from ade_bb_app_version, got: {match.group(1)!r}"
        )

    def test_cert_sans_exact_ade_pair(self):
        """The cert validation loop must contain the exact ade pair, not a
        loose substring that would pass on an unrelated hostname."""
        content = (COMPOSE_DIR / "bringup.yml").read_text()
        assert '"ade.cove" "ade.cove.local"' in content, (
            "bringup.yml cert validation must assert the exact ade.cove pair"
        )

    def test_hosts_entry_includes_ade_cove(self):
        content = (COMPOSE_DIR / "bringup.yml").read_text()
        assert "ade.cove ade.cove.local" in content, (
            "bringup.yml /etc/hosts line must include ade.cove ade.cove.local"
        )

    def test_creates_ade_data_directory(self):
        bringup = _load_bringup()
        tasks = bringup[0]["tasks"] if isinstance(bringup, list) else bringup.get("tasks", [])
        dir_loops = [
            t.get("loop", []) for t in tasks
            if isinstance(t, dict) and "data" in (t.get("name", "") or "").lower()
        ]
        assert any("ade" in str(item) for loop in dir_loops for item in loop), (
            "bringup.yml must create the ${cove_data_root}/ade data directory"
        )


class TestStatusOptionalServices:
    def test_ade_in_optional_services(self):
        from cove.status import OPTIONAL_SERVICES
        names = [c[0] for c in OPTIONAL_SERVICES]
        assert "cove-ade-server" in names, "ADE must be an optional service in status.py"

    def test_ade_profile_is_ade(self):
        from cove.status import OPTIONAL_SERVICES
        profile = [c[2] for c in OPTIONAL_SERVICES if c[0] == "cove-ade-server"]
        assert profile == ["ade"], f"ADE profile must be 'ade', got: {profile}"


class TestResourcesSync:
    def test_ade_bundled_resources_in_sync(self):
        if not RESOURCES_COMPOSE_DIR.is_dir():
            pytest.skip("cli/cove/resources/compose/ missing — run sync_compose_resources.py")
        for rel in ["docker-compose.yml", "bringup.yml", "ade/Dockerfile", "nginx/default.conf.j2"]:
            src = COMPOSE_DIR / rel
            dst = RESOURCES_COMPOSE_DIR / rel
            if not dst.exists():
                pytest.fail(f"bundled resources missing {rel} — run sync_compose_resources.py")
            assert src.read_bytes() == dst.read_bytes(), (
                f"bundled resources out of sync for {rel} — run sync_compose_resources.py"
            )
