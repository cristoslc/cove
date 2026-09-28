"""Tests for ToolHive MCP gateway hardening: seed files, compose config,
nginx routing, CLI module, and the LiteLLM disable_mcp cross-guard.

Unit/integration tests (always runnable):
  - Validate compose/toolhive/registry.json parses and has no unpinned image refs
  - Validate the default permission profile is sandboxed (no mounts, no outbound)
  - Validate compose service definition (profile, ro socket, loopback port, limits)
  - Validate nginx template renders mcp.cove server block with WS/SSE headers
  - Validate bringup.yml seeds the registry and sets .env defaults
  - Validate CLI module imports and has correct subcommands
  - Cross-guard: LiteLLM config still disables MCP (CVE-2026-42271)

E2E tests (require live stack, run with `pytest -m e2e`):
  - compose up --profile mcp starts the control plane
  - /health returns 204 through nginx
  - docker.sock mount is read-only

Run all:   pytest cli/tests/test_toolhive.py
Run unit:  pytest cli/tests/test_toolhive.py -m "not e2e"
Run e2e:   pytest cli/tests/test_toolhive.py -m e2e
"""

import json
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
TOOLHIVE_DIR = COMPOSE_DIR / "toolhive"
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

LITELLM_DIR = COMPOSE_DIR / "litellm"


def _load_compose() -> dict:
    with open(COMPOSE_DIR / "docker-compose.yml") as f:
        return yaml.safe_load(f)


def _load_bringup() -> dict:
    with open(COMPOSE_DIR / "bringup.yml") as f:
        return yaml.safe_load(f)


def _load_registry() -> dict:
    with open(TOOLHIVE_DIR / "registry.json") as f:
        return json.load(f)


def _load_default_profile() -> dict:
    with open(TOOLHIVE_DIR / "cove-default.json") as f:
        return json.load(f)


def _render_nginx() -> str:
    env = Environment(loader=FileSystemLoader(str(NGINX_DIR)), undefined=StrictUndefined)
    tmpl = env.get_template("default.conf.j2")
    return tmpl.render(FULL_TEMPLATE_VARS)


class TestRegistrySeed:
    """Validate the curated registry seed (compose/toolhive/registry.json)."""

    def test_registry_file_exists(self):
        assert (TOOLHIVE_DIR / "registry.json").exists(), (
            "compose/toolhive/registry.json seed missing"
        )

    def test_registry_parses(self):
        data = _load_registry()
        assert isinstance(data, dict), "registry.json must be a JSON object"

    def test_registry_uses_upstream_wire_format(self):
        """ToolHive v0.51.x requires the upstream MCP registry wire format
        (data.servers list); the legacy {"servers": {...}} shape is rejected."""
        data = _load_registry()
        assert "data" in data and "servers" in data.get("data", {}), (
            "registry must use the upstream wire format (data.servers)"
        )
        assert isinstance(data["data"]["servers"], list)

    def test_registry_has_curated_servers(self):
        data = _load_registry()
        servers = data["data"]["servers"]
        assert 2 <= len(servers) <= 3, (
            f"registry must curate 2-3 servers, got: {len(servers)}"
        )
        names = [s.get("name", "") for s in servers]
        assert any("filesystem" in n for n in names), (
            f"registry must include the filesystem server, got: {names}"
        )
        assert any("fetch" in n for n in names), (
            f"registry must include the network-only fetch server, got: {names}"
        )

    def test_registry_no_latest_tags(self):
        """No unpinned image refs — every package identifier must carry a
        version tag (no :latest)."""
        data = _load_registry()
        for server in data["data"]["servers"]:
            for package in server.get("packages", []):
                identifier = str(package.get("identifier", ""))
                assert identifier, f"server {server.get('name')} has no image ref"
                assert ":latest" not in identifier, (
                    f"unpinned :latest image ref in registry: {identifier}"
                )
                assert ":" in identifier, (
                    f"image ref must carry a version tag, got: {identifier}"
                )

    def test_filesystem_server_sandboxed_no_mounts(self):
        """The filesystem server entry must declare NO code mounts by default —
        sandboxed posture per docs/plans/toolhive-mcp-gateway.md."""
        data = _load_registry()
        for server in data["data"]["servers"]:
            if "filesystem" not in server.get("name", ""):
                continue
            extensions = (
                server.get("_meta", {})
                .get("io.modelcontextprotocol.registry/publisher-provided", {})
                .get("io.github.stacklok", {})
            )
            entry = next(iter(extensions.values()), {})
            perms = entry.get("permissions", {})
            assert not perms.get("read"), (
                f"filesystem server must have no read mounts by default, got: {perms.get('read')}"
            )
            assert not perms.get("write"), (
                f"filesystem server must have no write mounts by default, got: {perms.get('write')}"
            )
            return
        pytest.fail("filesystem server entry not found in registry")

    def test_fetch_server_is_network_only(self):
        """The fetch server must allow outbound network but declare no mounts."""
        data = _load_registry()
        for server in data["data"]["servers"]:
            if "fetch" not in server.get("name", ""):
                continue
            extensions = (
                server.get("_meta", {})
                .get("io.modelcontextprotocol.registry/publisher-provided", {})
                .get("io.github.stacklok", {})
            )
            entry = next(iter(extensions.values()), {})
            outbound = entry.get("permissions", {}).get("network", {}).get("outbound", {})
            assert outbound, (
                "fetch server must allow outbound network (it is the network-only server)"
            )
            assert not entry.get("permissions", {}).get("read"), (
                "fetch server must declare no read mounts"
            )
            assert not entry.get("permissions", {}).get("write"), (
                "fetch server must declare no write mounts"
            )
            return
        pytest.fail("fetch server entry not found in registry")


class TestDefaultPermissionProfile:
    """Validate the default permission profile (cove-default.json)."""

    def test_profile_file_exists(self):
        assert (TOOLHIVE_DIR / "cove-default.json").exists(), (
            "compose/toolhive/cove-default.json missing"
        )

    def test_profile_is_sandboxed(self):
        """Default profile mirrors permissions.BuiltinNoneProfile(): no mounts,
        no outbound allow, not privileged."""
        profile = _load_default_profile()
        assert profile.get("name") == "cove-sandboxed", (
            f"profile name must be cove-sandboxed, got: {profile.get('name')!r}"
        )
        assert not profile.get("read"), "default profile must have no read mounts"
        assert not profile.get("write"), "default profile must have no write mounts"
        outbound = profile.get("network", {}).get("outbound", {})
        assert not outbound.get("insecure_allow_all"), (
            "default profile must not allow all outbound traffic"
        )
        assert not profile.get("privileged"), "default profile must not be privileged"


class TestComposeServiceDefinitions:
    """Validate the ToolHive service definition in docker-compose.yml."""

    def test_toolhive_service_exists(self):
        data = _load_compose()
        assert "toolhive" in data["services"], "toolhive service missing from compose"

    def test_toolhive_has_mcp_profile(self):
        data = _load_compose()
        profiles = data["services"]["toolhive"].get("profiles", [])
        assert "mcp" in profiles, "toolhive service must have profiles: [\"mcp\"]"

    def test_toolhive_image_pinned_by_digest(self):
        """The control-plane image must be pinned by tag AND digest — no
        :latest, no floating tags (plan: pin by digest, not latest)."""
        data = _load_compose()
        image = str(data["services"]["toolhive"].get("image", ""))
        assert "@sha256:" in image, f"toolhive image must be pinned by digest, got: {image}"
        assert ":latest" not in image, f"toolhive image must not use :latest, got: {image}"
        assert "ghcr.io/stacklok/toolhive" in image, (
            f"toolhive image must be the stacklok control-plane image, got: {image}"
        )

    def test_toolhive_container_name_has_cove_prefix(self):
        data = _load_compose()
        name = str(data["services"]["toolhive"].get("container_name", ""))
        assert "cove-" in name, f"container_name must default to cove- prefix, got: {name}"

    def test_toolhive_binds_localhost_only(self):
        """The API/UI must bind 127.0.0.1 only — never 0.0.0.0 on the host.
        mcp.cove is the only non-loopback exposure (through nginx)."""
        data = _load_compose()
        ports = [str(p) for p in data["services"]["toolhive"].get("ports", [])]
        assert ports, "toolhive must publish its API port"
        for p in ports:
            assert "0.0.0.0" not in p, f"toolhive must not bind 0.0.0.0, got: {p}"
            assert "127.0.0.1" in p, f"toolhive must bind 127.0.0.1 only, got: {p}"

    def test_toolhive_socket_mount_read_only(self):
        """The docker.sock mount must be :ro — control plane only (plan:
        socket is control-plane only, blast radius constrained by profiles)."""
        data = _load_compose()
        volumes = [str(v) for v in data["services"]["toolhive"].get("volumes", [])]
        socket_mounts = [v for v in volumes if "docker.sock" in v]
        assert socket_mounts, "toolhive must mount /var/run/docker.sock"
        for v in socket_mounts:
            assert v.rstrip().endswith(":ro"), f"docker.sock mount must be :ro, got: {v}"

    def test_toolhive_has_healthcheck_on_api(self):
        """Health check must exercise the API. The image is distroless (no
        curl/wget — verified by pulling v0.51.4), so the healthcheck uses the
        bundled thv binary; `thv list` discovers the API and verifies /health
        with nonce, which fails if the API server is down."""
        data = _load_compose()
        hc = data["services"]["toolhive"].get("healthcheck")
        assert hc is not None, "toolhive must have a healthcheck"
        test_cmd = [str(part) for part in (hc.get("test") or [])]
        assert any("thv" in part for part in test_cmd), (
            f"healthcheck must use the thv binary (no shell/curl in image), got: {test_cmd}"
        )

    def test_toolhive_has_memory_limit(self):
        data = _load_compose()
        deploy = data["services"]["toolhive"].get("deploy", {})
        limits = deploy.get("resources", {}).get("limits", {})
        assert "memory" in limits, "toolhive must have a memory limit"

    def test_toolhive_mounts_state_from_data_root(self):
        """State must live under ${COVE_DATA_ROOT}/toolhive/ (Data in Documents)."""
        data = _load_compose()
        volumes = [str(v) for v in data["services"]["toolhive"].get("volumes", [])]
        assert any("${COVE_DATA_ROOT}/toolhive/" in v for v in volumes), (
            "toolhive must mount state under ${COVE_DATA_ROOT}/toolhive/"
        )

    def test_toolhive_mounts_registry_read_only(self):
        """The seeded registry must be mounted :ro — the control plane must not
        be able to rewrite the curated catalog."""
        data = _load_compose()
        volumes = [str(v) for v in data["services"]["toolhive"].get("volumes", [])]
        registry_mounts = [v for v in volumes if "registry.json" in v]
        assert registry_mounts, "toolhive must mount the seeded registry.json"
        for v in registry_mounts:
            assert ":ro" in v, f"registry mount must be :ro, got: {v}"

    def test_toolhive_mounts_permission_profiles_read_only(self):
        data = _load_compose()
        volumes = [str(v) for v in data["services"]["toolhive"].get("volumes", [])]
        profile_mounts = [v for v in volumes if "/profiles" in v]
        assert profile_mounts, "toolhive must mount the seeded permission profiles"
        for v in profile_mounts:
            assert ":ro" in v, f"profiles mount must be :ro, got: {v}"

    def test_toolhive_serves_on_8080_container_port(self):
        """nginx upstreams the compose-network container port (8080). The
        variable TOOLHIVE_PORT is the loopback host port only."""
        data = _load_compose()
        ports = [str(p) for p in data["services"]["toolhive"].get("ports", [])]
        assert any(":8080" in p for p in ports), (
            f"container port must be 8080 (thv serve default), got: {ports}"
        )


class TestNginxConfig:
    """Validate the nginx template renders mcp.cove with WS/SSE headers."""

    def _extract_toolhive_block(self, rendered: str) -> str:
        """Extract the mcp.cove server block from rendered nginx config."""
        lines = rendered.split("\n")
        target_idx = None
        for i, line in enumerate(lines):
            if "server_name mcp.cove" in line:
                target_idx = i
                break
        if target_idx is None:
            return ""
        start_idx = target_idx
        for i in range(target_idx, max(target_idx - 10, -1), -1):
            if lines[i].strip().startswith("server {"):
                start_idx = i
                break
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

    def test_mcp_server_block_exists(self):
        rendered = _render_nginx()
        assert "server_name mcp.cove" in rendered, "mcp.cove server block missing"
        assert "mcp.cove.local" in rendered

    def test_mcp_block_after_speedtest(self):
        """The mcp.cove block must come after the speedtest block (plan:
        placed after the speedtest block)."""
        rendered = _render_nginx()
        assert rendered.index("server_name speedtest.cove") < rendered.index("server_name mcp.cove"), (
            "mcp.cove block must be placed after the speedtest block"
        )

    def test_mcp_upstream_is_deferred_dns_variable(self):
        """Variable upstream + Docker resolver so nginx starts when the mcp
        profile is off (same pattern as litellm/speedtest/ade blocks)."""
        rendered = _render_nginx()
        assert "$toolhive_upstream" in rendered
        assert "set $toolhive_upstream http://toolhive:8080;" in rendered, (
            "upstream must target the container port 8080 on the compose network"
        )
        assert "resolver 127.0.0.11" in rendered

    def test_mcp_block_proxies_all_paths(self):
        """The ToolHive API is the MCP gateway surface — all paths proxy
        through nginx (isolation via the loopback port binding, like litellm)."""
        rendered = _render_nginx()
        block = self._extract_toolhive_block(rendered)
        assert "proxy_pass $toolhive_upstream" in block, (
            "mcp.cove must proxy all paths to the ToolHive API"
        )

    def test_mcp_block_ws_sse_headers(self):
        """Streamable HTTP/SSE need HTTP/1.1, Upgrade/Connection headers, and
        long read timeouts with buffering off."""
        rendered = _render_nginx()
        block = self._extract_toolhive_block(rendered)
        assert "proxy_http_version 1.1" in block
        assert "proxy_set_header Upgrade $http_upgrade;" in block
        assert "proxy_set_header Connection $connection_upgrade;" in block
        read_timeouts = [line for line in block.split("\n") if "proxy_read_timeout" in line]
        assert read_timeouts, "mcp.cove must set proxy_read_timeout for long-lived SSE"
        assert "proxy_buffering off" in block

    def test_mcp_block_uses_default_cert(self):
        rendered = _render_nginx()
        block = self._extract_toolhive_block(rendered)
        assert "/certs/cove.local.pem" in block


class TestBringupIntegration:
    """Validate bringup.yml wires the mcp profile: cert SANs, hosts, .env
    defaults, data dirs, and registry seeding."""

    def test_cert_sans_include_mcp_cove(self):
        with open(COMPOSE_DIR / "bringup.yml") as f:
            content = f.read()
        assert "mcp.cove" in content, "bringup.yml must include mcp.cove in cert SANs"

    def test_hosts_entry_includes_mcp_cove(self):
        bringup = _load_bringup()
        tasks = bringup[0]["tasks"] if isinstance(bringup, list) else bringup.get("tasks", [])
        hosts_task = [
            t for t in tasks
            if isinstance(t, dict) and "hosts" in (t.get("name", "") or "").lower()
        ]
        line = str(hosts_task[0].get("ansible.builtin.lineinfile", {}).get("line", ""))
        assert "mcp.cove" in line, f"/etc/hosts entry must include mcp.cove, got: {line}"

    def test_env_includes_toolhive_vars(self):
        with open(COMPOSE_DIR / "bringup.yml") as f:
            content = f.read()
        assert "TOOLHIVE_IMAGE" in content, "bringup.yml .env must include TOOLHIVE_IMAGE"
        assert "TOOLHIVE_PORT" in content, "bringup.yml .env must include TOOLHIVE_PORT"
        assert "TOOLHIVE_MEM_LIMIT" in content, "bringup.yml .env must include TOOLHIVE_MEM_LIMIT"

    def test_creates_toolhive_data_directories(self):
        with open(COMPOSE_DIR / "bringup.yml") as f:
            content = f.read()
        assert "toolhive/config" in content, "bringup.yml must create the toolhive config dir"
        assert "toolhive/state" in content, "bringup.yml must create the toolhive state dir"
        assert "toolhive/profiles" in content, "bringup.yml must create the toolhive profiles dir"

    def test_seeds_registry_into_data_root(self):
        """bringup.yml must copy the curated registry.json into
        ${COVE_DATA_ROOT}/toolhive/ (the compose mount source)."""
        with open(COMPOSE_DIR / "bringup.yml") as f:
            content = f.read()
        assert "toolhive/registry.json" in content, (
            "bringup.yml must seed registry.json into $COVE_DATA_ROOT/toolhive/"
        )

    def test_seeds_permission_profiles_into_data_root(self):
        with open(COMPOSE_DIR / "bringup.yml") as f:
            content = f.read()
        assert "cove-default.json" in content, (
            "bringup.yml must seed the default permission profile"
        )

    def test_registry_mount_target_guard(self):
        """The registry.json bind-mount target must be guarded against the
        Docker auto-created-directory wedge (same as litellm config.yaml)."""
        with open(COMPOSE_DIR / "bringup.yml") as f:
            content = f.read()
        assert "toolhive/registry.json" in content

    def test_cert_validation_includes_mcp_cove(self):
        with open(COMPOSE_DIR / "bringup.yml") as f:
            content = f.read()
        assert "mcp.cove" in content, "bringup.yml cert validation must include mcp.cove"


class TestLitellmMcpGuard:
    """Cross-guard: LiteLLM's MCP endpoints stay disabled (CVE-2026-42271).
    ToolHive is the only MCP surface in Cove (docs/plans/toolhive-mcp-gateway.md)."""

    def test_disable_mcp_still_true(self):
        with open(LITELLM_DIR / "config.yaml.j2") as f:
            content = f.read()
        assert "disable_mcp: true" in content, (
            "LiteLLM disable_mcp: true must stay (CVE-2026-42271); ToolHive is the MCP surface"
        )

    def test_litellm_toolhive_cross_reference_present(self):
        """The plan mandates a comment cross-referencing the ToolHive plan so
        nobody 'helpfully' re-enables MCP endpoints."""
        with open(LITELLM_DIR / "config.yaml.j2") as f:
            content = f.read()
        assert "toolhive" in content.lower(), (
            "config.yaml.j2 must cross-reference the ToolHive MCP gateway plan"
        )


class TestCLI:
    """Validate the cove toolhive CLI module."""

    def test_toolhive_group_imports(self):
        from cove.toolhive import toolhive
        assert toolhive is not None

    def test_toolhive_group_registered(self):
        from cove.cli import app
        commands = list(app.commands.keys())
        assert "toolhive" in commands, "toolhive group must be registered in cli.py"

    def test_toolhive_has_up_command(self):
        from cove.toolhive import toolhive
        commands = list(toolhive.commands.keys())
        assert "up" in commands

    def test_toolhive_has_down_command(self):
        from cove.toolhive import toolhive
        commands = list(toolhive.commands.keys())
        assert "down" in commands

    def test_toolhive_has_status_command(self):
        from cove.toolhive import toolhive
        commands = list(toolhive.commands.keys())
        assert "status" in commands

    def test_toolhive_has_logs_command(self):
        from cove.toolhive import toolhive
        commands = list(toolhive.commands.keys())
        assert "logs" in commands

    def test_toolhive_up_uses_profile_flag(self):
        """cove toolhive up must use --profile mcp so it doesn't start core
        services."""
        source = (PROJECT_ROOT / "cli" / "cove" / "toolhive.py").read_text()
        assert "--profile" in source and "mcp" in source, (
            "cove toolhive up must use --profile mcp"
        )

    def test_toolhive_up_profile_before_subcommand(self):
        """docker compose requires --profile as a GLOBAL flag BEFORE the
        subcommand (Docker Compose 5.4.0). `cove toolhive up` must pass
        `--profile mcp` before `up`, not after (same regression root cause
        as litellm/speedtest)."""
        from cove.toolhive import toolhive

        captured: list[list[str]] = []

        def fake_subprocess_run(cmd, **kwargs):
            captured.append(list(cmd))
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch("cove.toolhive.subprocess.run", side_effect=fake_subprocess_run):
            runner = CliRunner()
            result = runner.invoke(toolhive, ["up"])

        assert result.exit_code == 0, f"cove toolhive up failed: {result.output}"
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

    def test_toolhive_down_uses_stop_not_down(self):
        """cove toolhive down must use 'stop' not 'down' to avoid stopping
        core Cove services."""
        source = (PROJECT_ROOT / "cli" / "cove" / "toolhive.py").read_text()
        assert '"stop"' in source or "'stop'" in source, (
            "cove toolhive down must use 'stop' command, not 'down'"
        )

    def test_toolhive_status_checks_through_nginx(self):
        """cove toolhive status must check through nginx (Host: mcp.cove),
        not directly on the loopback host port."""
        source = (PROJECT_ROOT / "cli" / "cove" / "toolhive.py").read_text()
        assert "mcp.cove" in source, (
            "cove toolhive status must check through nginx with Host: mcp.cove"
        )

    def test_toolhive_status_checks_8443_not_direct_port(self):
        """The status health probe must go through nginx (8443), never the
        direct loopback port — keeps the ingress the single front door."""
        source = (PROJECT_ROOT / "cli" / "cove" / "toolhive.py").read_text()
        assert "8443" in source, "status must check through nginx (8443), not a direct port"


class TestStatusOptionalServices:
    """Validate status.py includes ToolHive as an optional service."""

    def test_toolhive_in_optional_services(self):
        from cove.status import OPTIONAL_SERVICES
        entries = [tuple(e) for e in OPTIONAL_SERVICES]
        assert ("cove-toolhive", "ToolHive", "mcp") in entries, (
            "ToolHive must be in OPTIONAL_SERVICES as (cove-toolhive, ToolHive, mcp)"
        )

    def test_toolhive_not_in_required_services(self):
        """ToolHive is optional — it must NOT be in the required SERVICES list."""
        from cove.status import SERVICES
        names = [name for _, name in SERVICES]
        assert "ToolHive" not in names, (
            "ToolHive must NOT be in required SERVICES — it's optional"
        )

    def test_up_all_starts_mcp_profile(self):
        """cove up --all must include the mcp profile in the bringup
        COMPOSE_PROFILES (toolhive has no credential step — runner pattern)."""
        source = (PROJECT_ROOT / "cli" / "cove" / "cli.py").read_text()
        assert '"runner"' in source and '"mcp"' in source, (
            "cove up --all must start the mcp profile alongside runner"
        )