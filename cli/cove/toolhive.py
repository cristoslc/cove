"""CLI commands for ToolHive MCP gateway lifecycle."""

import subprocess

import click

from cove.constants import NGINX_HTTPS_PORT
from cove.stateless import resolve_compose_dir


TOOLHIVE_URL = "https://mcp.cove/"


def _compose_cmd(*args: str) -> list[str]:
    compose_dir = resolve_compose_dir()
    return [
        "docker", "compose",
        "--project-directory", str(compose_dir),
        *args,
    ]


@click.group()
def toolhive():
    """Manage the ToolHive MCP gateway (optional harbor service).

    ToolHive is the Cove MCP gateway: it runs sibling MCP-server containers
    constrained by permission profiles and explicit mounts. It serves at
    https://mcp.cove/ and is reached only through the nginx ingress; the
    API/UI binds 127.0.0.1 only. See docs/services/toolhive.md.
    """


@toolhive.command()
def up():
    """Start the ToolHive MCP gateway control plane.

    No credential step in phase 1 (per-server secrets are Phase 2, seeded
    from Vault via `cove creds`); the curated registry and default permission
    profile are seeded by `cove up` from bringup.yml."""
    click.echo("Starting ToolHive MCP gateway...")
    subprocess.run(_compose_cmd("--profile", "mcp", "up", "-d"), check=True)
    click.echo(f"ToolHive is running at {TOOLHIVE_URL}")


@toolhive.command()
def down():
    """Stop the ToolHive MCP gateway (workload data preserved).

    compose stop only stops the toolhive control plane; any thv-spawned
    sibling MCP-server workload containers keep running until stopped
    via the ToolHive API (a Phase 2 `cove mcp` hook owns that lifecycle).
    """
    click.echo("Stopping ToolHive MCP gateway...")
    subprocess.run(_compose_cmd("stop", "toolhive"), check=True)
    click.echo("ToolHive MCP gateway stopped.")


@toolhive.command()
def status():
    """Check ToolHive MCP gateway health."""
    result = subprocess.run(
        _compose_cmd("ps", "--format", "table {{.Name}}\t{{.Status}}\t{{.Ports}}"),
        capture_output=True, text=True,
    )
    click.echo(result.stdout)
    if result.returncode != 0:
        if result.stderr:
            click.echo(result.stderr)
        raise SystemExit(result.returncode)

    click.echo("Checking mcp.cove through nginx...")
    for host in ("mcp.cove.local", "mcp.cove"):
        health = subprocess.run(
            ["curl", "-sf", "-H", f"Host: {host}", f"https://127.0.0.1:{NGINX_HTTPS_PORT}/health"],
            capture_output=True, text=True, timeout=10,
        )
        if health.returncode == 0:
            click.echo("  Health: OK")
            return
    click.echo("  Health: UNREACHABLE")
    raise SystemExit(1)


@toolhive.command()
@click.option("-n", "--lines", default=50, help="Number of lines to show.")
@click.option("-f", "--follow", is_flag=True, help="Follow log output.")
def logs(lines, follow):
    """Tail ToolHive MCP gateway logs."""
    cmd = _compose_cmd("logs", "--tail", str(lines))
    if follow:
        cmd.append("--follow")
    subprocess.run(cmd, check=True)
