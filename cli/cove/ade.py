"""CLI commands for the ADE bb server lifecycle."""

import os
import subprocess

import click

from cove.stateless import resolve_compose_dir


ADE_SERVICE = "ade"
ADE_CONTAINER_NAME = "cove-ade-server"
ADE_URL = "https://ade.cove/"
ADE_HEALTH_PORT = 8443


def _container_name() -> str:
    return os.environ.get("ADE_CONTAINER_NAME", ADE_CONTAINER_NAME)


def _compose_cmd(*args: str) -> list[str]:
    compose_dir = resolve_compose_dir()
    return [
        "docker", "compose",
        "--project-directory", str(compose_dir),
        *args,
    ]


def _run_checked(cmd: list[str], action: str) -> None:
    try:
        subprocess.run(cmd, check=True)
    except FileNotFoundError as exc:
        raise click.ClickException(
            f"docker is not installed or not on PATH: {exc}"
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise click.ClickException(
            f"docker compose {action} failed (exit {exc.returncode})."
        ) from exc


@click.group()
def ade():
    """Manage the ADE bb server (agentic harness, core service).

    The ADE runs the pinned `bb-app` server in a container on the cove
    network and serves the bb web UI at https://ade.cove/ through nginx.
    It starts with `cove up` (no profile needed since 0.8.0); `down` stops
    it until the next `cove up`. Direct-URL mode carries no application
    auth: the trust boundary is the Cove network and ingress. See
    docs/services/ade.md.
    """


@ade.command()
def up():
    """Ensure the ADE bb server is built and running."""
    click.echo("Starting ADE bb server...")
    _run_checked(_compose_cmd("up", "-d", "--build", ADE_SERVICE), "up")
    click.echo(f"ADE bb server is running at {ADE_URL}")


@ade.command()
def down():
    """Stop the ADE bb server (data preserved)."""
    click.echo("Stopping ADE bb server...")
    _run_checked(_compose_cmd("stop", ADE_SERVICE), "stop")
    click.echo("ADE bb server stopped.")


@ade.command()
def status():
    """Check ADE bb server health."""
    result = subprocess.run(
        _compose_cmd("ps", "--format", "table {{.Name}}\t{{.Status}}\t{{.Ports}}", ADE_SERVICE),
        capture_output=True, text=True,
    )
    click.echo(result.stdout)
    if result.returncode != 0:
        if result.stderr:
            click.echo(result.stderr)
        raise SystemExit(result.returncode)

    if _container_name() not in result.stdout:
        click.echo(f"  Health: NOT RUNNING (container {_container_name()} absent)")
        raise SystemExit(1)

    for host in ("ade.cove.local", "ade.cove"):
        try:
            health = subprocess.run(
                ["curl", "-sf", "-H", f"Host: {host}", f"https://127.0.0.1:{ADE_HEALTH_PORT}/health"],
                capture_output=True, text=True, timeout=10,
            )
        except subprocess.TimeoutExpired:
            continue
        if health.returncode == 0:
            click.echo("  Health: OK")
            return
    click.echo("  Health: UNREACHABLE")
    raise SystemExit(1)


@ade.command()
@click.option("-n", "--lines", default=50, help="Number of lines to show.")
@click.option("-f", "--follow", is_flag=True, help="Follow log output.")
def logs(lines, follow):
    """Tail ADE bb server logs."""
    cmd = _compose_cmd("logs", "--tail", str(lines), ADE_SERVICE)
    if follow:
        cmd.append("--follow")
    subprocess.run(cmd, check=True)
