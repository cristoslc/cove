"""CLI commands for Speedtest Tracker lifecycle."""

import os
import subprocess

import click

from cove.stateless import resolve_compose_dir


def _require_app_key() -> None:
    """Fail loud if SPEEDTEST_APP_KEY is unset or empty.

    APP_KEY is a required secret (no weak default) used to encrypt stored data.
    """
    if not os.environ.get("SPEEDTEST_APP_KEY"):
        raise click.ClickException(
            "SPEEDTEST_APP_KEY must be set before starting Speedtest Tracker. "
            "Generate one with: export SPEEDTEST_APP_KEY=\"base64:$(openssl rand -base64 32)\""
        )


def _compose_cmd(*args: str) -> list[str]:
    compose_dir = resolve_compose_dir()
    return [
        "docker", "compose",
        "--project-directory", str(compose_dir),
        *args,
    ]


@click.group()
def speedtest():
    """Manage the Speedtest Tracker (optional WAN-link monitor).

    Speedtest Tracker monitors the machine's internet connection —
    uptime, latency, and bandwidth. It runs on https://speedtest.cove/
    and is reached only through the nginx ingress.
    """


@speedtest.command()
def up():
    """Start the Speedtest Tracker service."""
    _require_app_key()
    click.echo("Starting Speedtest Tracker...")
    subprocess.run(_compose_cmd("up", "-d", "--profile", "speedtest"), check=True)
    click.echo("Speedtest Tracker is running at https://speedtest.cove/")


@speedtest.command()
def down():
    """Stop the Speedtest Tracker service (data preserved)."""
    click.echo("Stopping Speedtest Tracker...")
    subprocess.run(_compose_cmd("stop", "speedtest-tracker"), check=True)
    click.echo("Speedtest Tracker stopped.")


@speedtest.command()
def status():
    """Check Speedtest Tracker health."""
    result = subprocess.run(
        _compose_cmd("ps", "--filter", "name=cove-speedtest-tracker",
                     "--format", "table {{.Name}}\t{{.Status}}\t{{.Ports}}"),
        capture_output=True, text=True,
    )
    click.echo(result.stdout)
    if result.returncode != 0:
        raise SystemExit(result.returncode)

    click.echo("Checking speedtest.cove through nginx...")
    for host in ("speedtest.cove.local", "speedtest.cove"):
        health = subprocess.run(
            ["curl", "-sf", "-H", f"Host: {host}", "https://127.0.0.1:8443/"],
            capture_output=True, text=True, timeout=10,
        )
        if health.returncode == 0:
            click.echo("  Health: OK")
            return
    click.echo("  Health: UNREACHABLE")
    raise SystemExit(1)


@speedtest.command()
@click.option("-n", "--lines", default=50, help="Number of lines to show.")
@click.option("-f", "--follow", is_flag=True, help="Follow log output.")
def logs(lines, follow):
    """Tail Speedtest Tracker logs."""
    cmd = _compose_cmd("logs", "--tail", str(lines))
    if follow:
        cmd.append("--follow")
    subprocess.run(cmd, check=True)
