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