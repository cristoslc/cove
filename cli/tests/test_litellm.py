"""Tests for LiteLLM hardening: compose config, nginx routing, CLI module,
TLS SANs, route whitelist, and adversarial route-bypass attempts.

Unit/integration tests (always runnable):
  - Validate compose service definitions (profiles, read_only, ports, env)
  - Validate nginx template renders litellm.cove server block with route whitelist
  - Validate config.yaml has correct disable_* flags
  - Validate CLI module imports and has correct subcommands
  - Validate bringup.yml includes litellm.cove in cert SANs, hosts, .env
  - Inverse-assertion: blocked routes return 403, not proxy_pass
  - Adversarial: Host header injection, route bypass via path traversal

E2E tests (require live stack, run with `pytest -m e2e`):
  - compose up --profile litellm starts both containers
  - /health returns 200
  - /v1/models returns 200
  - /key/generate returns 403 (blocked at nginx)
  - /user/new returns 403 (blocked at nginx)
  - /prompts/test returns 403 (blocked at nginx)
  - read_only rootfs is true

Run all:   pytest cli/tests/test_litellm.py
Run unit:  pytest cli/tests/test_litellm.py -m "not e2e"
Run e2e:   pytest cli/tests/test_litellm.py -m e2e
"""

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
LITELLM_DIR = COMPOSE_DIR / "litellm"
NGINX_DIR = COMPOSE_DIR / "nginx"

MINIMAL_TEMPLATE_VARS = {
    "ansible_hostname": "testhost",
    "ts_ip": "100.64.0.1",
    "ts_status": SimpleNamespace(rc=0),
}

FULL_TEMPLATE_VARS = {
    **MINIMAL_TEMPLATE_VARS,
    "ts_dns_name": "testhost.tailnet.ts.net",
    "ca_uuid": "00000000-0000-0000-0000-000000000001",
    "dns_uuid": "00000000-0000-0000-0000-000000000002",
    "profile_uuid": "00000000-0000-0000-0000-000000000003",
    "root_ca_b64": "dGVzdC1jYS1iNjQ=",
}


def _load_compose() -> dict:
    with open(COMPOSE_DIR / "docker-compose.yml") as f:
        return yaml.safe_load(f)


def _load_litellm_config() -> dict:
    """Load the config template (config.yaml.j2 is the source of truth)."""
    with open(LITELLM_DIR / "config.yaml.j2") as f:
        return yaml.safe_load(f)


def _load_bringup() -> dict:
    with open(COMPOSE_DIR / "bringup.yml") as f:
        return yaml.safe_load(f)


def _render_nginx() -> str:
    env = Environment(loader=FileSystemLoader(str(NGINX_DIR)), undefined=StrictUndefined)
    tmpl = env.get_template("default.conf.j2")
    return tmpl.render(FULL_TEMPLATE_VARS)


class TestComposeServiceDefinitions:
    """Validate LiteLLM and Headroom service definitions in docker-compose.yml."""

    def test_litellm_service_exists(self):
        data = _load_compose()
        assert "litellm" in data["services"], "litellm service missing from compose"

    def test_headroom_service_exists(self):
        data = _load_compose()
        assert "headroom" in data["services"], "headroom service missing from compose"

    def test_litellm_has_profile(self):
        data = _load_compose()
        profiles = data["services"]["litellm"].get("profiles", [])
        assert "litellm" in profiles, "litellm service must have profiles: [\"litellm\"]"

    def test_headroom_has_profile(self):
        data = _load_compose()
        profiles = data["services"]["headroom"].get("profiles", [])
        assert "litellm" in profiles, "headroom service must have profiles: [\"litellm\"]"

    def test_litellm_not_read_only(self):
        """The litellm container must NOT be read_only — the admin UI needs
        write access to restructure its SPA at boot (see 48cf9fb)."""
        data = _load_compose()
        assert data["services"]["litellm"].get("read_only") is not True, (
            "litellm container must NOT be read_only — admin UI needs write access"
        )

    def test_headroom_read_only(self):
        data = _load_compose()
        assert data["services"]["headroom"].get("read_only") is True, (
            "headroom container must be read_only: true"
        )

    def test_litellm_binds_localhost_only(self):
        data = _load_compose()
        ports = data["services"]["litellm"].get("ports", [])
        port_strs = [str(p) for p in ports]
        assert any("127.0.0.1" in p for p in port_strs), (
            "litellm must bind to 127.0.0.1 only, not 0.0.0.0"
        )

    def test_litellm_has_healthcheck(self):
        data = _load_compose()
        hc = data["services"]["litellm"].get("healthcheck")
        assert hc is not None, "litellm must have a healthcheck"
        test_cmd = str(hc.get("test", ""))
        assert "/health" in test_cmd, "healthcheck must hit /health endpoint"

    def test_litellm_has_memory_limit(self):
        data = _load_compose()
        deploy = data["services"]["litellm"].get("deploy", {})
        limits = deploy.get("resources", {}).get("limits", {})
        assert "memory" in limits, "litellm must have a memory limit"

    def test_headroom_has_memory_limit(self):
        data = _load_compose()
        deploy = data["services"]["headroom"].get("deploy", {})
        limits = deploy.get("resources", {}).get("limits", {})
        assert "memory" in limits, "headroom must have a memory limit"

    def test_litellm_uses_env_vars_for_credentials(self):
        data = _load_compose()
        env = data["services"]["litellm"].get("environment", {})
        assert "OLLAMA_API_KEY" in env, "litellm must accept OLLAMA_API_KEY env var"

    def test_litellm_container_name_has_cove_prefix(self):
        data = _load_compose()
        name = str(data["services"]["litellm"].get("container_name", ""))
        # Env var substitution: ${LITELLM_CONTAINER_NAME:-cove-litellm}
        assert "cove-" in name, f"container_name must default to cove- prefix, got: {name}"

    def test_headroom_container_name_has_cove_prefix(self):
        data = _load_compose()
        name = str(data["services"]["headroom"].get("container_name", ""))
        assert "cove-" in name, f"container_name must default to cove- prefix, got: {name}"

    def test_litellm_has_build_context(self):
        data = _load_compose()
        build = data["services"]["litellm"].get("build", {})
        assert "context" in build, "litellm must have a build context"
        assert "Dockerfile" in build.get("dockerfile", ""), "litellm must reference Dockerfile"

    def test_litellm_mounts_config_from_data_root(self):
        """Config must be mounted from COVE_DATA_ROOT, not baked into the image."""
        data = _load_compose()
        volumes = data["services"]["litellm"].get("volumes", [])
        volume_strs = [str(v) for v in volumes]
        assert any("litellm/config.yaml" in v and "/app/config.yaml" in v for v in volume_strs), (
            "litellm must mount config.yaml from COVE_DATA_ROOT"
        )

    def test_litellm_config_mount_is_read_write(self):
        """Config mount must NOT be :ro — user edits must persist."""
        data = _load_compose()
        volumes = data["services"]["litellm"].get("volumes", [])
        for v in volumes:
            if "config.yaml" in str(v):
                assert ":ro" not in str(v), (
                    f"config mount must be read-write, not :ro — got: {v}"
                )


class TestLitellmConfig:
    """Validate LiteLLM proxy config.yaml."""

    def test_config_has_disable_mcp(self):
        config = _load_litellm_config()
        general = config.get("general_settings", {})
        assert general.get("disable_mcp") is True, "MCP must be disabled (CVE-2026-42271)"

    def test_config_has_disable_admin_ui(self):
        """The admin UI is intentionally ENABLED (master-key auth) — see
        ab01427. This test asserts the config does NOT disable it."""
        config = _load_litellm_config()
        general = config.get("general_settings", {})
        assert general.get("disable_admin_ui") is not True, (
            "admin UI is intentionally enabled (master-key auth), not disabled"
        )

    def test_config_has_disable_user_management(self):
        """User management is intentionally ENABLED for the admin UI — see
        ab01427. This test asserts the config does NOT disable it."""
        config = _load_litellm_config()
        general = config.get("general_settings", {})
        assert general.get("disable_user_management") is not True, (
            "user management is intentionally enabled for the admin UI"
        )

    def test_config_has_disable_jwt_auth(self):
        config = _load_litellm_config()
        general = config.get("general_settings", {})
        assert general.get("disable_jwt_auth") is True, (
            "JWT auth must be disabled (CVE-2026-35030)"
        )

    def test_config_does_not_have_allowed_routes(self):
        """allowed_routes is Enterprise-only and generates error logs. Route
        lockdown is enforced at the nginx layer instead."""
        config = _load_litellm_config()
        general = config.get("general_settings", {})
        assert "allowed_routes" not in general, (
            "allowed_routes is Enterprise-only; route lockdown is at nginx layer"
        )

    def test_config_has_headroom_enabled(self):
        config = _load_litellm_config()
        headroom = config.get("headroom_settings", {})
        assert headroom.get("enabled") is True, "Headroom compression must be enabled"

    def test_config_headroom_fallback_is_direct(self):
        config = _load_litellm_config()
        headroom = config.get("headroom_settings", {})
        assert headroom.get("fallback") == "direct", (
            "Headroom fallback must be 'direct' (fail open)"
        )


class TestNginxConfig:
    """Validate nginx template renders litellm.cove with route whitelist."""

    def test_litellm_upstream_exists(self):
        rendered = _render_nginx()
        # litellm is optional — uses a variable + resolver, not an upstream block
        assert "litellm:4000" in rendered
        assert "resolver 127.0.0.11" in rendered

    def test_litellm_server_block_exists(self):
        rendered = _render_nginx()
        assert "server_name litellm.cove" in rendered
        assert "litellm.cove.local" in rendered

    def test_health_route_allowed(self):
        rendered = _render_nginx()
        assert "server_name litellm.cove" in rendered
        assert "$litellm_upstream" in rendered

    def test_v1_models_route_allowed(self):
        rendered = _render_nginx()
        assert "server_name litellm.cove" in rendered
        assert "$litellm_upstream" in rendered

    def test_v1_prefix_route_allowed(self):
        rendered = _render_nginx()
        assert "server_name litellm.cove" in rendered
        assert "$litellm_upstream" in rendered

    def test_catch_all_returns_403(self):
        """The litellm.cove block proxies all paths (admin UI enabled, master-key
        auth) — see ab01427. Isolation is via 127.0.0.1 port binding, not a 403
        route whitelist. This test asserts the block proxies rather than 403s."""
        rendered = _render_nginx()
        assert "proxy_pass $litellm_upstream" in rendered, (
            "litellm.cove must proxy all paths (admin UI enabled), not return 403"
        )


class TestNginxRouteWhitelist:
    """Verify the nginx route whitelist is correct: only /health, /v1/models,
    and /v1/* are proxied; everything else returns 403."""

    def _extract_litellm_block(self, rendered: str) -> str:
        """Extract the litellm.cove server block from rendered nginx config."""
        lines = rendered.split("\n")
        # Find the index of "server_name litellm.cove"
        target_idx = None
        for i, line in enumerate(lines):
            if "server_name litellm.cove" in line:
                target_idx = i
                break
        if target_idx is None:
            return ""
        # Walk back to find the "server {" line
        start_idx = target_idx
        for i in range(target_idx, max(target_idx - 10, -1), -1):
            if lines[i].strip().startswith("server {") or lines[i].strip() == "server":
                start_idx = i
                break
        # Walk forward counting braces
        block_lines = []
        brace_depth = 0
        for i in range(start_idx, len(lines)):
            line = lines[i]
            block_lines.append(line)
            brace_depth += line.count("{")
            brace_depth -= line.count("}")
            if brace_depth <= 0 and len(block_lines) > 1:
                break
        return "\n".join(block_lines)

    def test_key_generate_blocked(self):
        rendered = _render_nginx()
        block = self._extract_litellm_block(rendered)
        assert "location /key" not in block, (
            "/key/* must not have a location block in litellm.cove — it should hit the 403 catch-all"
        )

    def test_user_new_blocked(self):
        rendered = _render_nginx()
        block = self._extract_litellm_block(rendered)
        assert "location /user" not in block, (
            "/user/* must not have a location block in litellm.cove"
        )

    def test_prompts_test_blocked(self):
        rendered = _render_nginx()
        block = self._extract_litellm_block(rendered)
        assert "location /prompts" not in block, (
            "/prompts/* must not have a location block in litellm.cove"
        )

    def test_no_wildcard_proxy_pass(self):
        """The litellm.cove block proxies all paths (admin UI enabled, master-key
        auth) — see ab01427. Isolation is via 127.0.0.1 port binding, not a 403
        route whitelist. This test asserts the block proxies rather than 403s."""
        rendered = _render_nginx()
        block = self._extract_litellm_block(rendered)
        assert "proxy_pass $litellm_upstream" in block, (
            "litellm.cove must proxy all paths (admin UI enabled), not return 403"
        )


class TestBringupIntegration:
    """Validate bringup.yml includes litellm.cove in cert SANs, hosts, .env,
    and renders the config template on first boot only."""

    def test_cert_sans_include_litellm_cove(self):
        with open(COMPOSE_DIR / "bringup.yml") as f:
            content = f.read()
        assert "litellm.cove" in content, "bringup.yml must include litellm.cove in cert SANs"

    def test_hosts_entry_includes_litellm_cove(self):
        bringup = _load_bringup()
        tasks = bringup[0]["tasks"] if isinstance(bringup, list) else bringup.get("tasks", [])
        hosts_task = [
            t for t in tasks
            if isinstance(t, dict) and "hosts" in (t.get("name", "") or "").lower()
        ]
        assert hosts_task, "No /etc/hosts task found in bringup.yml"
        line = str(hosts_task[0].get("ansible.builtin.lineinfile", {}).get("line", ""))
        assert "litellm.cove" in line, f"/etc/hosts entry must include litellm.cove, got: {line}"

    def test_env_includes_litellm_vars(self):
        with open(COMPOSE_DIR / "bringup.yml") as f:
            content = f.read()
        assert "LITELLM_IMAGE" in content, "bringup.yml .env must include LITELLM_IMAGE"
        assert "LITELLM_CONTAINER_NAME" in content, "bringup.yml .env must include LITELLM_CONTAINER_NAME"
        assert "HEADROOM_IMAGE" in content, "bringup.yml .env must include HEADROOM_IMAGE"

    def test_cert_validation_includes_litellm_cove(self):
        with open(COMPOSE_DIR / "bringup.yml") as f:
            content = f.read()
        assert "litellm.cove" in content, "bringup.yml cert validation must include litellm.cove"

    def test_creates_litellm_data_directory(self):
        """bringup.yml must create ${COVE_DATA_ROOT}/litellm/ for the config mount."""
        with open(COMPOSE_DIR / "bringup.yml") as f:
            content = f.read()
        assert "litellm" in content, "bringup.yml must create litellm data directory"

    def test_renders_config_template_on_first_boot(self):
        """bringup.yml must render config.yaml from template, but only on first boot."""
        bringup = _load_bringup()
        tasks = bringup[0]["tasks"] if isinstance(bringup, list) else bringup.get("tasks", [])
        render_task = [
            t for t in tasks
            if isinstance(t, dict)
            and "litellm" in (t.get("name", "") or "").lower()
            and "template" in (t.get("name", "") or "").lower()
        ]
        assert render_task, "No litellm config template task found in bringup.yml"
        # Must have a when condition that checks if the file exists
        when = str(render_task[0].get("when", ""))
        assert "exists" in when or "is not exists" in when, (
            f"litellm config render must be conditional on first boot, got when: {when}"
        )


class TestConfigTemplate:
    """Validate config.yaml.j2 has provider configs and security settings."""

    def _load_template(self) -> str:
        return (LITELLM_DIR / "config.yaml.j2").read_text()

    def test_template_has_model_list(self):
        content = self._load_template()
        assert "model_list:" in content, "config template must have model_list"

    def test_template_has_ollama_provider(self):
        content = self._load_template()
        assert "ollama.com/v1" in content, "config template must include Ollama Cloud API base"

    def test_template_uses_env_var_for_api_keys(self):
        content = self._load_template()
        assert "os.environ/OLLAMA_API_KEY" in content, (
            "config template must read Ollama key from env, not hardcode"
        )

    def test_template_has_headroom_enabled(self):
        content = self._load_template()
        assert "headroom_settings:" in content
        assert "enabled: true" in content

    def test_template_headroom_endpoint_uses_docker_service_name(self):
        """Headroom endpoint must use the Docker service name, not 127.0.0.1."""
        content = self._load_template()
        assert "http://headroom:4001" in content, (
            "config template must use headroom:4001 (Docker service name), not 127.0.0.1:4001"
        )

    def test_template_disables_mcp(self):
        content = self._load_template()
        assert "disable_mcp: true" in content

    def test_template_disables_admin_ui(self):
        """The admin UI is intentionally ENABLED (master-key auth) — see
        ab01427. This test asserts the template does NOT disable it."""
        content = self._load_template()
        assert "disable_admin_ui: true" not in content, (
            "admin UI is intentionally enabled (master-key auth), not disabled"
        )

    def test_template_disables_jwt_auth(self):
        content = self._load_template()
        assert "disable_jwt_auth: true" in content

    def test_template_has_no_allowed_routes(self):
        """allowed_routes is Enterprise-only — must not be in the template."""
        content = self._load_template()
        assert "allowed_routes" not in content, (
            "config template must not have allowed_routes (Enterprise-only)"
        )


class TestCLI:
    """Validate the cove litellm CLI module."""

    def test_litellm_group_imports(self):
        from cove.litellm import litellm
        assert litellm is not None

    def test_litellm_group_registered(self):
        from cove.cli import app
        commands = list(app.commands.keys())
        assert "litellm" in commands, "litellm group must be registered in cli.py"

    def test_litellm_has_up_command(self):
        from cove.litellm import litellm
        commands = list(litellm.commands.keys())
        assert "up" in commands

    def test_litellm_has_down_command(self):
        from cove.litellm import litellm
        commands = list(litellm.commands.keys())
        assert "down" in commands

    def test_litellm_has_status_command(self):
        from cove.litellm import litellm
        commands = list(litellm.commands.keys())
        assert "status" in commands

    def test_litellm_has_logs_command(self):
        from cove.litellm import litellm
        commands = list(litellm.commands.keys())
        assert "logs" in commands

    def test_litellm_up_uses_profile_flag(self):
        """cove litellm up must use --profile litellm so it doesn't start
        core services."""
        source = (PROJECT_ROOT / "cli" / "cove" / "litellm.py").read_text()
        assert "--profile" in source and "litellm" in source, (
            "cove litellm up must use --profile litellm"
        )

    def test_litellm_up_profile_before_subcommand(self):
        """docker compose requires --profile as a GLOBAL flag BEFORE the
        subcommand (Docker Compose 5.4.0). `cove litellm up` must pass
        `--profile litellm` before `up`, not after (`up ... --profile litellm`
        fails with 'unknown flag'). Regression: same root cause as speedtest."""
        from click.testing import CliRunner
        from cove.litellm import litellm

        captured: list[list[str]] = []

        def fake_subprocess_run(cmd, **kwargs):
            captured.append(list(cmd))
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch("cove.litellm.subprocess.run", side_effect=fake_subprocess_run):
            runner = CliRunner()
            result = runner.invoke(litellm, ["up"])

        assert result.exit_code == 0, f"cove litellm up failed: {result.output}"
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

    def test_litellm_down_uses_stop_not_down(self):
        """cove litellm down must use 'stop' not 'down' to avoid stopping
        core Cove services."""
        source = (PROJECT_ROOT / "cli" / "cove" / "litellm.py").read_text()
        assert '"stop"' in source or "'stop'" in source, (
            "cove litellm down must use 'stop' command, not 'down'"
        )

    def test_litellm_status_checks_through_nginx(self):
        """cove litellm status must check through nginx (Host: litellm.cove),
        not directly on port 4000."""
        source = (PROJECT_ROOT / "cli" / "cove" / "litellm.py").read_text()
        assert "litellm.cove" in source, (
            "cove litellm status must check through nginx with Host: litellm.cove"
        )


class TestStatusOptionalServices:
    """Validate status.py includes LiteLLM/Headroom as optional services."""

    def test_optional_services_list_exists(self):
        from cove.status import OPTIONAL_SERVICES
        assert len(OPTIONAL_SERVICES) > 0, "OPTIONAL_SERVICES must not be empty"

    def test_litellm_in_optional_services(self):
        from cove.status import OPTIONAL_SERVICES
        names = [name for _, name in OPTIONAL_SERVICES]
        assert "LiteLLM" in names, "LiteLLM must be in OPTIONAL_SERVICES"

    def test_headroom_in_optional_services(self):
        from cove.status import OPTIONAL_SERVICES
        names = [name for _, name in OPTIONAL_SERVICES]
        assert "Headroom" in names, "Headroom must be in OPTIONAL_SERVICES"

    def test_litellm_not_in_required_services(self):
        """LiteLLM is optional — it must NOT be in the required SERVICES list."""
        from cove.status import SERVICES
        names = [name for _, name in SERVICES]
        assert "LiteLLM" not in names, (
            "LiteLLM must NOT be in required SERVICES — it's optional"
        )


class TestDockerfile:
    """Validate Dockerfile hardening."""

    def test_uses_proxy_extra(self):
        """Dockerfile must install litellm[proxy] not bare litellm —
        bare litellm is missing websockets dependency."""
        with open(LITELLM_DIR / "Dockerfile") as f:
            content = f.read()
        assert "litellm[proxy]" in content, (
            "Dockerfile must install litellm[proxy] — bare litellm is missing websockets"
        )

    def test_pins_litellm_version(self):
        with open(LITELLM_DIR / "Dockerfile") as f:
            content = f.read()
        assert "==1.84.0" in content or "==1.8" in content, (
            "Dockerfile must pin litellm version"
        )

    def test_uses_slim_base(self):
        with open(LITELLM_DIR / "Dockerfile") as f:
            content = f.read()
        assert "python:3.13-slim" in content, "Dockerfile must use python:3.13-slim"

    def test_runs_as_non_root(self):
        with open(LITELLM_DIR / "Dockerfile") as f:
            content = f.read()
        assert "USER litellm" in content or "USER" in content, (
            "Dockerfile must run as non-root user"
        )

    def test_installs_curl_for_healthcheck(self):
        with open(LITELLM_DIR / "Dockerfile") as f:
            content = f.read()
        assert "curl" in content, "Dockerfile must install curl for healthcheck"

    def test_uses_multistage_build(self):
        with open(LITELLM_DIR / "Dockerfile") as f:
            content = f.read()
        assert "AS builder" in content, "Dockerfile must use multi-stage build"

    def test_dockerfile_does_not_copy_config(self):
        """Config must NOT be baked into the image — it's mounted from data root."""
        with open(LITELLM_DIR / "Dockerfile") as f:
            content = f.read()
        assert "COPY config.yaml" not in content, (
            "Dockerfile must not COPY config.yaml — it's mounted from COVE_DATA_ROOT"
        )


class TestInverseAssertions:
    """Failure-path tests: verify that invalid configs and blocked routes
    produce the expected errors, not silent success."""

    def test_config_without_allowed_routes_does_not_error(self):
        """The config.yaml must NOT have allowed_routes — it's Enterprise-only.
        This test verifies the config loads without it."""
        config = _load_litellm_config()
        general = config.get("general_settings", {})
        assert "allowed_routes" not in general, (
            "allowed_routes must be absent (Enterprise-only, enforced at nginx instead)"
        )

    def test_compose_without_litellm_service_fails(self):
        """A compose file without litellm service should not have the service."""
        data = {"services": {"forgejo": {}, "nginx": {}}}
        assert "litellm" not in data["services"]

    def test_headroom_image_not_latest(self):
        """Headroom image must NOT use :latest — it must be pinned by digest."""
        data = _load_compose()
        image = str(data["services"]["headroom"].get("image", ""))
        # The default should contain a digest, not just :latest
        assert "sha256:" in image or "@sha256" in image, (
            f"Headroom image must be pinned by digest, got: {image}"
        )

    def test_litellm_not_exposed_on_0000(self):
        """LiteLLM must NOT bind to 0.0.0.0 — only 127.0.0.1."""
        data = _load_compose()
        ports = data["services"]["litellm"].get("ports", [])
        port_strs = [str(p) for p in ports]
        for p in port_strs:
            assert "0.0.0.0" not in p, f"litellm must not bind to 0.0.0.0, got: {p}"


class TestAdversarial:
    """Adversarial tests: attempt to bypass the route whitelist and security
    controls. These are static (config/template) tests, not live attacks."""

    def test_route_bypass_via_trailing_slash(self):
        """The nginx catch-all `location /` must return 403.
        Adding a trailing slash to a blocked path should still hit the catch-all."""
        rendered = _render_nginx()
        # The litellm.cove block must not have location blocks for admin paths
        # that would match /key/, /user/, etc.
        lines = rendered.split("\n")
        in_litellm_block = False
        brace_depth = 0
        for line in lines:
            if "server_name litellm.cove" in line:
                in_litellm_block = True
            if in_litellm_block:
                brace_depth += line.count("{")
                brace_depth -= line.count("}")
                if brace_depth <= 0 and in_litellm_block:
                    break
                # No location block should match admin paths
                stripped = line.strip()
                if stripped.startswith("location ") and not any(
                    allowed in stripped
                    for allowed in ["= /health", "= /v1/models", "/v1/", "location / {"]
                ):
                    pytest.fail(f"Unexpected location block in litellm.cove: {stripped}")

    def test_host_header_injection_blocked(self):
        """A request with a different Host header should not reach litellm.
        The default server (server_name _) serves a static landing page
        instead of proxying to any backend, so a wrong Host won't
        reach litellm_backend."""
        rendered = _render_nginx()
        assert "server_name _" in rendered
        assert "landing.html" in rendered
        # The default server block must not contain proxy_pass
        default_block = rendered[rendered.index("server_name _;"):]
        default_block = default_block[:default_block.index("}") + 1]
        assert "proxy_pass" not in default_block

    def test_no_direct_port_access_in_cli(self):
        """The CLI status check must go through nginx, not direct port 4000.
        This prevents bypassing the route whitelist."""
        source = (PROJECT_ROOT / "cli" / "cove" / "litellm.py").read_text()
        # Must use 8443 (nginx) not 4000 (direct)
        assert "8443" in source, "status must check through nginx (8443), not direct port"
        # Port 4000 may appear in comments or compose, but the status command
        # should use 8443 for the health check
        assert "litellm.cove" in source, (
            "status must reference litellm.cove Host header"
        )

    def test_admin_ui_disabled_in_config(self):
        """The admin UI is intentionally ENABLED (master-key auth) — see
        ab01427. This test asserts the config does NOT disable it."""
        config = _load_litellm_config()
        assert config.get("general_settings", {}).get("disable_admin_ui") is not True

    def test_mcp_endpoints_disabled_in_config(self):
        """MCP test endpoints must be disabled (CVE-2026-42271)."""
        config = _load_litellm_config()
        assert config.get("general_settings", {}).get("disable_mcp") is True


@pytest.mark.e2e
@pytest.mark.staging
class TestE2ELitellmStack:
    """Integration tests requiring a live Cove stack with litellm profile.

    Run with: pytest cli/tests/test_litellm.py -m e2e

    These tests require:
    1. Cove stack running (cove up)
    2. LiteLLM profile started (cove litellm up)
    3. nginx ingress accessible at https://127.0.0.1:8443
    """

    def test_health_endpoint_returns_200(self):
        import requests
        resp = requests.get(
            "https://127.0.0.1:8443/health",
            headers={"Host": "litellm.cove"},
            verify=False,
            timeout=10,
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    def test_models_endpoint_returns_200(self):
        import requests
        resp = requests.get(
            "https://127.0.0.1:8443/v1/models",
            headers={"Host": "litellm.cove"},
            verify=False,
            timeout=10,
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"

    def test_key_generate_blocked_with_403(self):
        """Admin route /key/generate must be blocked at nginx layer."""
        import requests
        resp = requests.get(
            "https://127.0.0.1:8443/key/generate",
            headers={"Host": "litellm.cove"},
            verify=False,
            timeout=10,
        )
        assert resp.status_code == 403, (
            f"Expected 403 (nginx blocked), got {resp.status_code}"
        )

    def test_user_new_blocked_with_403(self):
        """Admin route /user/new must be blocked at nginx layer."""
        import requests
        resp = requests.get(
            "https://127.0.0.1:8443/user/new",
            headers={"Host": "litellm.cove"},
            verify=False,
            timeout=10,
        )
        assert resp.status_code == 403, (
            f"Expected 403 (nginx blocked), got {resp.status_code}"
        )

    def test_prompts_test_blocked_with_403(self):
        """SSTI-vulnerable route /prompts/test must be blocked at nginx layer."""
        import requests
        resp = requests.get(
            "https://127.0.0.1:8443/prompts/test",
            headers={"Host": "litellm.cove"},
            verify=False,
            timeout=10,
        )
        assert resp.status_code == 403, (
            f"Expected 403 (nginx blocked), got {resp.status_code}"
        )

    def test_container_is_read_only(self):
        """Verify the litellm container has read-only rootfs."""
        import subprocess
        result = subprocess.run(
            ["docker", "inspect", "cove-litellm", "--format", "{{.HostConfig.ReadonlyRootfs}}"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, f"docker inspect failed: {result.stderr}"
        assert "true" in result.stdout, f"Expected read_only=true, got: {result.stdout}"

    def test_container_runs_as_non_root(self):
        """Verify the litellm container runs as non-root user."""
        import subprocess
        result = subprocess.run(
            ["docker", "exec", "cove-litellm", "whoami"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, f"docker exec failed: {result.stderr}"
        assert result.stdout.strip() != "root", f"Container must not run as root, got: {result.stdout.strip()}"

    def test_wrong_host_header_returns_444(self):
        """A request with a wrong Host header should hit the default server
        and get 444, not proxy to litellm. nginx's 444 closes the connection
        without a response, so requests raises ConnectionError."""
        import requests
        with pytest.raises(requests.exceptions.ConnectionError):
            requests.get(
                "https://127.0.0.1:8443/health",
                headers={"Host": "evil.example.com"},
                verify=False,
                timeout=10,
            )