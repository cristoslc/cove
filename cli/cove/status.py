"""Health checks for cove services."""

import json
import logging
import subprocess
import urllib3
from dataclasses import dataclass, field
from pathlib import Path

import click
import requests

from cove.constants import NGINX_HTTP_PORT, NGINX_HTTPS_PORT
from cove.resolver import (
    corrective_command,
    drifted_resolver_files,
    expected_dnsmasq_port,
    is_macos,
)
from cove.stateless import resolve_compose_dir

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logging.getLogger("urllib3").setLevel(logging.ERROR)


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""
    hints: list[str] = field(default_factory=list)
    optional: bool = False


SERVICES = [
    ("cove-forgejo", "Forgejo"),
    ("cove-nginx", "nginx"),
    ("cove-vault", "Vault"),
    ("cove-dnsmasq", "dnsmasq"),
    ("cove-dnsproxy", "dnsproxy"),
    # Core since 0.8.0 (operator decision 2026-09-25, ADR-018): the ADE
    # ships as part of Cove — `cove up` starts it, a stopped ADE fails status.
    ("cove-ade-server", "ADE"),
]

OPTIONAL_SERVICES = [
    ("cove-litellm", "LiteLLM", "litellm"),
    ("cove-headroom", "Headroom", "litellm"),
    ("cove-speedtest-tracker", "Speedtest", "speedtest"),
    ("cove-forgejo-runner", "Runner", "runner"),
    ("cove-toolhive", "ToolHive", "mcp"),
]

# The HTTPS port constant lives in cove.constants and is re-exported here for
# existing importers. Port coupling points that must stay equal to it:
#   - compose/docker-compose.yml (hardcoded 0.0.0.0:443:443 publish)
#   - compose/group_vars/all.yml (nginx_https_port, Ansible-rendered probe URLs)
NGINX_HTTPS_PORT = NGINX_HTTPS_PORT
NGINX_HTTP_PORT = NGINX_HTTP_PORT


def _docker_ps() -> dict[str, dict]:
    result = subprocess.run(
        ["docker", "ps", "--format", "{{json .}}"],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode != 0:
        return {}
    containers: dict[str, dict] = {}
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        try:
            info = json.loads(line)
            containers[info.get("Names", info.get("ID", ""))] = info
        except json.JSONDecodeError:
            pass
    return containers


def _check_containers() -> list[CheckResult]:
    containers = _docker_ps()
    results: list[CheckResult] = []
    for container_name, label in SERVICES:
        info = containers.get(container_name)
        if info is None:
            results.append(CheckResult(
                name=label,
                ok=False,
                detail=f"Container {container_name} is not running",
                hints=[f"Run `docker compose --project-directory ... up -d {container_name.split('-', 1)[1] or container_name}`"],
            ))
        else:
            status = info.get("Status", "unknown")
            results.append(CheckResult(
                name=label,
                ok=True,
                detail=status,
            ))
    for container_name, label, profile in OPTIONAL_SERVICES:
        info = containers.get(container_name)
        if info is None:
            results.append(CheckResult(
                name=label,
                ok=False,
                detail=f"Container {container_name} is not running (optional)",
                hints=[f"Run `cove {profile} up` to start it"],
                optional=True,
            ))
        else:
            status = info.get("Status", "unknown")
            results.append(CheckResult(
                name=label,
                ok=True,
                detail=status,
            ))
    return results


def _check_nginx_ingress() -> CheckResult:
    for host in ("hc.cove.local", "hc.cove"):
        try:
            resp = requests.get(
                f"https://127.0.0.1:{NGINX_HTTPS_PORT}/",
                headers={"Host": host},
                verify=False,
                timeout=10,
            )
            if resp.status_code == 200:
                return CheckResult(name="nginx ingress", ok=True, detail=resp.text.strip())
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            continue
    return CheckResult(
        name="nginx ingress",
        ok=False,
        detail=f"Connection refused on 127.0.0.1:{NGINX_HTTPS_PORT}",
        hints=[
            f"Is port {NGINX_HTTPS_PORT} free? Run `sudo lsof -i :{NGINX_HTTPS_PORT}` "
            "(unprivileged lsof cannot see root listeners like tailscaled)",
            "Check nginx: `docker logs cove-nginx`",
            "Is nginx up? Run `cove up`",
        ],
    )


def _check_forgejo() -> CheckResult:
    for host in ("git.cove.local", "git.cove"):
        try:
            resp = requests.get(
                f"https://127.0.0.1:{NGINX_HTTPS_PORT}/api/healthz",
                headers={"Host": host},
                verify=False,
                timeout=10,
            )
            if resp.status_code == 200:
                return CheckResult(name="Forgejo API", ok=True, detail=resp.text.strip())
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            continue
    return CheckResult(
        name="Forgejo API",
        ok=False,
        detail="Connection refused",
        hints=["Is Forgejo running? `docker ps | grep cove-forgejo`"],
    )


def _check_vault() -> CheckResult:
    for host in ("vault.cove.local", "vault.cove"):
        try:
            resp = requests.get(
                f"https://127.0.0.1:{NGINX_HTTPS_PORT}/v1/sys/health",
                headers={"Host": host},
                verify=False,
                timeout=10,
            )
            if resp.status_code == 200:
                return CheckResult(name="Vault API", ok=True, detail="initialized, unsealed")
            if resp.status_code == 501:
                return CheckResult(name="Vault API", ok=False, detail="not initialized")
            if resp.status_code == 503:
                return CheckResult(name="Vault API", ok=False, detail="sealed")
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            continue
    return CheckResult(
        name="Vault API",
        ok=False,
        detail="Connection refused",
        hints=["Is Vault running? `docker ps | grep cove-vault`"],
    )


def _check_dns() -> CheckResult:
    for name in ("git.cove.local", "git.cove"):
        try:
            result = subprocess.run(
                ["dscacheutil", "-q", "host", "-a", "name", name],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and "127.0.0.1" in result.stdout:
                return CheckResult(name="DNS resolution", ok=True, detail=f"{name} → 127.0.0.1")
        except subprocess.TimeoutExpired:
            continue
    return CheckResult(
        name="DNS resolution",
        ok=False,
        detail="git.cove.local / git.cove does not resolve to 127.0.0.1",
        hints=[
            "Check /etc/hosts: `grep cove /etc/hosts`",
            "Check /etc/resolver/cove",
            "Run `cove sudo enable` then `cove up` to configure DNS",
        ],
    )


def _check_resolver_port() -> CheckResult | None:
    """macOS only: fail loudly when a scoped-resolver file under /etc/resolver
    still points at an old dnsmasq port.

    `cove up` re-points every existing /etc/resolver/cove* file at
    `dnsmasq_port` on each run when it can (Darwin task + become), so a
    mismatch here means the write path was unavailable (a no-TTY run without
    passwordless sudo) or was bypassed. The hint carries the exact corrective
    one-liner. Returns None on other platforms, when there is no drift, or when
    the expected port cannot be determined — the DNS-resolution check below
    still covers a resolver that is broken outright.
    """
    if not is_macos():
        return None
    try:
        compose_dir = resolve_compose_dir()
        expected = expected_dnsmasq_port(compose_dir)
        drifted = drifted_resolver_files(expected)
    except (OSError, RuntimeError, ValueError, click.ClickException):
        return None
    if not drifted:
        return None
    stale = ", ".join(
        f"{path.name} (port {found})" for path, found in sorted(drifted.items())
    )
    return CheckResult(
        name="resolver port",
        ok=False,
        detail=f"/etc/resolver/cove* disagrees with dnsmasq_port={expected}: {stale}",
        hints=[
            f"Fix: {corrective_command(expected)}",
            "Or run `cove sudo enable` then `cove up` to re-point them automatically",
        ],
    )


def check_all() -> list[CheckResult]:
    results: list[CheckResult] = []
    results.extend(_check_containers())
    results.append(_check_nginx_ingress())
    results.append(_check_forgejo())
    results.append(_check_vault())
    results.append(_check_dns())
    # Only surfaces a row when there is drift; the check stays silent when the
    # resolver files already track dnsmasq_port (or there is none to compare).
    resolver_port = _check_resolver_port()
    if resolver_port is not None:
        results.append(resolver_port)
    return results


def print_status(results: list[CheckResult]) -> None:
    ok_count = sum(1 for r in results if r.ok)
    total = len(results)
    click.echo(f"\n{'='*50}")
    click.echo(f"Cove Status: {ok_count}/{total} checks passed")
    click.echo(f"{'='*50}")
    for r in results:
        icon = "✓" if r.ok else "✗"
        click.echo(f"  {icon} {r.name}: {r.detail}")
        if not r.ok and r.hints:
            for hint in r.hints:
                click.echo(f"     → {hint}")
    click.echo(f"{'='*50}\n")
