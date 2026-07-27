"""CLI commands for LiteLLM proxy lifecycle."""

import subprocess

import click

from cove.stateless import resolve_compose_dir


def _compose_cmd(*args: str) -> list[str]:
    compose_dir = resolve_compose_dir()
    return [
        "docker", "compose",
        "--project-directory", str(compose_dir),
        *args,
    ]


@click.group()
def litellm():
    """Manage the LiteLLM proxy (optional harbor service).

    LiteLLM is a hardened LLM proxy with Headroom compression.
    It runs on https://litellm.cove/ and proxies to upstream providers.
    """


@litellm.command()
def up():
    """Start the LiteLLM proxy and Headroom sidecar."""
    click.echo("Starting LiteLLM proxy...")
    subprocess.run(_compose_cmd("up", "-d", "--profile", "litellm"), check=True)
    click.echo("LiteLLM proxy is running at https://litellm.cove/")


@litellm.command()
def down():
    """Stop the LiteLLM proxy and Headroom sidecar."""
    click.echo("Stopping LiteLLM proxy...")
    subprocess.run(_compose_cmd("stop", "litellm", "headroom"), check=True)
    click.echo("LiteLLM proxy stopped.")


@litellm.command()
def status():
    """Check LiteLLM proxy health."""
    result = subprocess.run(
        _compose_cmd("ps", "--filter", "name=cove-litellm", "--filter", "name=cove-headroom",
                     "--format", "table {{.Name}}\t{{.Status}}\t{{.Ports}}"),
        capture_output=True, text=True,
    )
    click.echo(result.stdout)
    if result.returncode != 0:
        raise SystemExit(result.returncode)

    click.echo("Checking /health endpoint...")
    for host in ("litellm.cove.local", "litellm.cove"):
        health = subprocess.run(
            ["curl", "-sf", "-H", f"Host: {host}", "https://127.0.0.1:8443/health"],
            capture_output=True, text=True, timeout=10,
        )
        if health.returncode == 0:
            click.echo("  Health: OK")
            return
    click.echo("  Health: UNREACHABLE")
    raise SystemExit(1)


@litellm.command()
@click.option("-n", "--lines", default=50, help="Number of lines to show.")
@click.option("-f", "--follow", is_flag=True, help="Follow log output.")
def logs(lines, follow):
    """Tail LiteLLM proxy logs."""
    cmd = _compose_cmd("logs", "--tail", str(lines))
    if follow:
        cmd.append("--follow")
    subprocess.run(cmd, check=True)
