"""Staging-isolation contract for the `cove-staging` compose project.

The isolated staging mode (scripts/staging/deploy-isolated.sh) runs the branch
as a PARALLEL compose project (`-p cove-staging`) in the same Colima VM instead
of deploying into the live stack. These tests render

    docker compose -p cove-staging -f docker-compose.yml \
                   -f docker-compose.staging.yml [--profile ...] config

and assert the isolation contract:

  1. project name is cove-staging (even when someone omits -p),
  2. no container_name equals a live container name,
  3. no published host port collides with a live host port,
  4. nginx HTTPS is remapped to 127.0.0.1:9443,
  5. no bind-mount source touches the live data root,
  6. the staging nginx volume list keeps base mount targets in sync.

Tier 0 (unit/config): needs the `docker` compose CLI for rendering but NOT a
running daemon, so it runs in the default gate.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest


def _project_root() -> Path:
    start = Path(__file__).resolve().parent
    for _ in range(6):
        if (start / "compose" / "inventory.yml").exists():
            return start
        start = start.parent
    raise RuntimeError(f"Cannot find project root from {__file__}")


PROJECT_ROOT = _project_root()
COMPOSE_DIR = PROJECT_ROOT / "compose"
BASE_COMPOSE = COMPOSE_DIR / "docker-compose.yml"
STAGING_OVERRIDE = COMPOSE_DIR / "docker-compose.staging.yml"

# Live container names observed on this machine (docker ps, 2026-09-25).
# The staging project must never produce any of these names.
LIVE_CONTAINER_NAMES = {
    "cove-nginx",
    "cove-forgejo",
    "cove-vault",
    "cove-dnsmasq",
    "cove-dnsproxy",
    "cove-ade-server",
    "cove-litellm",
    "cove-litellm-db",
    "cove-headroom",
    "cove-speedtest-tracker",
    "cove-forgejo-runner",
    "cove-tunnel",
}

# Live host ports observed on this machine (docker ps, 2026-09-25):
# nginx 8443/tcp + 8080/tcp + 80/tcp, dnsmasq 5353/udp, forgejo ssh 2222,
# litellm 4000, headroom 4001, speedtest 8982.
LIVE_HOST_PORTS = {"80", "8080", "8443", "5353", "2222", "4000", "4001", "8982"}

# The live stack's data root (never mounted, never written by staging).
LIVE_DATA_ROOT = Path("~/Documents/cove-data").expanduser()

ALL_PROFILES = ["ade", "litellm", "speedtest", "runner", "tunnel"]

pytestmark = pytest.mark.skipif(
    shutil.which("docker") is None, reason="docker compose CLI not available"
)


def _render(*, profiles: list[str] | None = None, with_override: bool = True,
            project: str | None = "cove-staging", tmp_root: Path) -> dict:
    """Render merged compose config to a dict (client-side, no daemon)."""
    cmd = ["docker", "compose"]
    if project is not None:
        cmd += ["-p", project]
    cmd += ["-f", str(BASE_COMPOSE)]
    if with_override:
        assert STAGING_OVERRIDE.exists(), (
            f"missing staging override file: {STAGING_OVERRIDE}"
        )
        cmd += ["-f", str(STAGING_OVERRIDE)]
    for profile in profiles or []:
        cmd += ["--profile", profile]
    cmd += ["config", "--format", "json"]

    env = dict(os.environ)
    fake_staging_root = tmp_root / "cove-data-staging"
    env["COVE_DATA_ROOT"] = str(fake_staging_root)
    env["FORGEJO_DATA_ROOT"] = str(fake_staging_root)
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=120)
    assert proc.returncode == 0, (
        f"compose config failed ({' '.join(cmd)}):\n{proc.stderr}"
    )
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def fake_roots(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("staging-isolation")


@pytest.fixture(scope="module")
def ade_config(fake_roots) -> dict:
    """Rendered config for the isolated staging bring-up set (--profile ade)."""
    return _render(profiles=["ade"], tmp_root=fake_roots)


@pytest.fixture(scope="module")
def full_config(fake_roots) -> dict:
    """Rendered config with EVERY profile enabled (full-stack collision check)."""
    return _render(profiles=ALL_PROFILES, tmp_root=fake_roots)


@pytest.fixture(scope="module")
def base_nginx_volumes(fake_roots) -> set[str]:
    """Base-only render: nginx mount targets before the staging override."""
    cfg = _render(profiles=["ade"], with_override=False, tmp_root=fake_roots)
    return {v["target"] for v in cfg["services"]["nginx"].get("volumes", [])}


def _published_ports(cfg: dict) -> set[str]:
    """Every host-side published port across all rendered services."""
    ports: set[str] = set()
    for svc in cfg["services"].values():
        for p in svc.get("ports") or []:
            published = p.get("published")
            if published:
                ports.add(str(published))
    return ports


def _bind_sources(cfg: dict) -> list[str]:
    sources = []
    for svc in cfg["services"].values():
        for v in svc.get("volumes") or []:
            if v.get("type") == "bind":
                sources.append(os.path.expanduser(v["source"]))
    return sources


class TestProjectName:
    def test_project_name_with_p_flag(self, ade_config):
        assert ade_config["name"] == "cove-staging"

    def test_project_name_defensive_without_p_flag(self, fake_roots):
        """Even without -p, the override file's `name:` must replace `cove`."""
        cfg = _render(profiles=["ade"], project=None, tmp_root=fake_roots)
        assert cfg["name"] == "cove-staging"


class TestContainerNames:
    def test_ade_set_never_matches_live(self, ade_config):
        for svc, spec in ade_config["services"].items():
            name = spec.get("container_name")
            assert name, f"service {svc} has no container_name"
            assert name not in LIVE_CONTAINER_NAMES, (
                f"staging container name '{name}' (service {svc}) collides with live"
            )

    def test_full_stack_never_matches_live(self, full_config):
        for svc, spec in full_config["services"].items():
            name = spec.get("container_name")
            assert name, f"service {svc} has no container_name"
            assert name not in LIVE_CONTAINER_NAMES, (
                f"staging container name '{name}' (service {svc}) collides with live"
            )

    def test_all_names_use_staging_prefix(self, full_config):
        for svc, spec in full_config["services"].items():
            name = spec.get("container_name") or ""
            assert re.fullmatch(r"cove-staging-[a-z0-9-]+", name), (
                f"staging container name '{name}' (service {svc}) lacks "
                f"the cove-staging- prefix"
            )


class TestHostPorts:
    def test_nginx_https_remapped_to_9443_loopback(self, ade_config):
        ports = ade_config["services"]["nginx"].get("ports") or []
        assert ports == [
            {
                "mode": "ingress",
                "host_ip": "127.0.0.1",
                "target": 443,
                "published": "9443",
                "protocol": "tcp",
            }
        ], f"nginx staging ports not remapped to 127.0.0.1:9443: {ports}"

    def test_ade_set_no_live_port_collisions(self, ade_config):
        collisions = _published_ports(ade_config) & LIVE_HOST_PORTS
        assert not collisions, (
            f"staging (ade set) publishes live ports: {sorted(collisions)}"
        )

    def test_full_stack_no_live_port_collisions(self, full_config):
        collisions = _published_ports(full_config) & LIVE_HOST_PORTS
        assert not collisions, (
            f"staging (full stack) publishes live ports: {sorted(collisions)}"
        )


class TestDataRootIsolation:
    def test_no_bind_mount_under_live_data_root(self, full_config):
        live_prefix = str(LIVE_DATA_ROOT) + os.sep
        offenders = [
            s for s in _bind_sources(full_config)
            if s == str(LIVE_DATA_ROOT) or s.startswith(live_prefix)
        ]
        assert not offenders, (
            f"staging mounts paths under the live data root "
            f"({LIVE_DATA_ROOT}): {offenders}"
        )

    def test_staging_mounts_use_staging_data_root(self, ade_config, fake_roots):
        staging_root = str(fake_roots / "cove-data-staging")
        data_mounted = [
            s for s in _bind_sources(ade_config) if s.startswith(staging_root)
        ]
        assert data_mounted, "no staging bind mounts resolved from COVE_DATA_ROOT"


class TestOverrideDrift:
    def test_nginx_mount_targets_match_base(self, ade_config, base_nginx_volumes):
        """The override redefines nginx volumes; targets must match base exactly
        so a future base mount addition cannot be silently dropped in staging."""
        staging_targets = {
            v["target"] for v in ade_config["services"]["nginx"].get("volumes", [])
        }
        assert staging_targets == base_nginx_volumes
