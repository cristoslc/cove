"""Health checks for cove services."""

import json
import logging
import subprocess
import urllib3
from dataclasses import dataclass, field
from pathlib import Path

import requests

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logging.getLogger("urllib3").setLevel(logging.ERROR)


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""
    hints: list[str] = field(default_factory=list)


SERVICES = [
    ("cove-forgejo", "Forgejo"),
    ("cove-nginx", "nginx"),
    ("cove-vault", "Vault"),
    ("cove-dnsmasq", "dnsmasq"),
    ("cove-dnsproxy", "dnsproxy"),
]

OPTIONAL_SERVICES = [
    ("cove-litellm", "LiteLLM"),
    ("cove-headroom", "Headroom"),
]

NGINX_HTTPS_PORT = 8443
NGINX_HTTP_PORT = 8080


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
    for container_name, label in OPTIONAL_SERVICES:
        info = containers.get(container_name)
        if info is None:
            results.append(CheckResult(
                name=label,
                ok=True,
                detail=f"Container {container_name} is not running (optional)",
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
    try:
        resp = requests.get(
            f"https://127.0.0.1:{NGINX_HTTPS_PORT}/",
            headers={"Host": "hc.cove"},
            verify=False,
            timeout=10,
        )
        if resp.status_code == 200:
            return CheckResult(name="nginx ingress", ok=True, detail=resp.text.strip())
        return CheckResult(
            name="nginx ingress",
            ok=False,
            detail=f"HTTP {resp.status_code}",
            hints=["Check nginx logs: `docker logs cove-nginx`"],
        )
    except requests.exceptions.ConnectionError:
        return CheckResult(
            name="nginx ingress",
            ok=False,
            detail="Connection refused on 127.0.0.1:8443",
            hints=[
                "Is port 8443 free? Run `lsof -i :8443`",
                "Check nginx: `docker logs cove-nginx`",
                "Run `cove up` with sudo to configure pf 443→8443",
            ],
        )
    except requests.exceptions.Timeout:
        return CheckResult(
            name="nginx ingress",
            ok=False,
            detail="Connection timed out on 127.0.0.1:8443",
            hints=["Check nginx: `docker logs cove-nginx`"],
        )


def _check_forgejo() -> CheckResult:
    try:
        resp = requests.get(
            f"https://127.0.0.1:{NGINX_HTTPS_PORT}/api/healthz",
            headers={"Host": "git.cove"},
            verify=False,
            timeout=10,
        )
        if resp.status_code == 200:
            return CheckResult(name="Forgejo API", ok=True, detail=resp.text.strip())
        return CheckResult(
            name="Forgejo API",
            ok=False,
            detail=f"HTTP {resp.status_code}",
            hints=["Check Forgejo logs: `docker logs cove-forgejo`"],
        )
    except requests.exceptions.ConnectionError:
        return CheckResult(
            name="Forgejo API",
            ok=False,
            detail="Connection refused",
            hints=["Is Forgejo running? `docker ps | grep cove-forgejo`"],
        )
    except requests.exceptions.Timeout:
        return CheckResult(
            name="Forgejo API",
            ok=False,
            detail="Connection timed out",
            hints=["Check Forgejo logs: `docker logs cove-forgejo`"],
        )


def _check_vault() -> CheckResult:
    try:
        resp = requests.get(
            f"https://127.0.0.1:{NGINX_HTTPS_PORT}/v1/sys/health",
            headers={"Host": "vault.cove"},
            verify=False,
            timeout=10,
        )
        if resp.status_code == 200:
            return CheckResult(name="Vault API", ok=True, detail="initialized, unsealed")
        if resp.status_code == 501:
            return CheckResult(name="Vault API", ok=False, detail="not initialized")
        if resp.status_code == 503:
            return CheckResult(name="Vault API", ok=False, detail="sealed")
        return CheckResult(
            name="Vault API",
            ok=False,
            detail=f"HTTP {resp.status_code}",
            hints=["Check Vault logs: `docker logs cove-vault`"],
        )
    except requests.exceptions.ConnectionError:
        return CheckResult(
            name="Vault API",
            ok=False,
            detail="Connection refused",
            hints=["Is Vault running? `docker ps | grep cove-vault`"],
        )
    except requests.exceptions.Timeout:
        return CheckResult(
            name="Vault API",
            ok=False,
            detail="Connection timed out",
            hints=["Check Vault logs: `docker logs cove-vault`"],
        )


def _check_dns() -> CheckResult:
    try:
        result = subprocess.run(
            ["dscacheutil", "-q", "host", "-a", "name", "git.cove"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and "127.0.0.1" in result.stdout:
            return CheckResult(name="DNS resolution", ok=True, detail="git.cove → 127.0.0.1")
        return CheckResult(
            name="DNS resolution",
            ok=False,
            detail="git.cove does not resolve to 127.0.0.1",
            hints=[
                "Check /etc/hosts: `grep cove /etc/hosts`",
                "Check /etc/resolver/cove",
                "Run `cove up` with sudo to configure DNS",
            ],
        )
    except subprocess.TimeoutExpired:
        return CheckResult(
            name="DNS resolution",
            ok=False,
            detail="dscacheutil timed out",
        )


def check_all() -> list[CheckResult]:
    results: list[CheckResult] = []
    results.extend(_check_containers())
    results.append(_check_nginx_ingress())
    results.append(_check_forgejo())
    results.append(_check_vault())
    results.append(_check_dns())
    return results


def print_status(results: list[CheckResult]) -> None:
    import click
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
