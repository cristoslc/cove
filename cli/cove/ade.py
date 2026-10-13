"""CLI commands for the ADE bb server lifecycle."""

import os
import re
import subprocess
import time

import click
import requests

from cove.constants import NGINX_HTTPS_PORT
from cove.stateless import resolve_compose_dir


ADE_SERVICE = "ade"
ADE_CONTAINER_NAME = "cove-ade-server"
ADE_URL = "https://ade.cove/"
NPM_LATEST_URL = "https://registry.npmjs.org/bb-app/latest"
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$")


def _container_name() -> str:
    return os.environ.get("ADE_CONTAINER_NAME", ADE_CONTAINER_NAME)


def _compose_env_path():
    return resolve_compose_dir() / ".env"


def _read_env_key(key: str) -> str | None:
    """Return KEY's value from the compose .env, or None if absent/empty."""
    env_path = _compose_env_path()
    if not env_path.exists():
        return None
    for line in env_path.read_text().splitlines():
        if line.startswith(f"{key}="):
            value = line.split("=", 1)[1].strip()
            return value or None
    return None


def _upsert_env(key: str, value: str) -> None:
    """Set KEY=VALUE in the compose .env idempotently (single line).

    ADE_BB_APP_VERSION / ADE_IMAGE are deliberately NOT re-synced by bringup
    (only ADE_PORT/ADE_CONTAINER_NAME are), so a version written here persists
    across `cove up` — it is the supported runtime override surface for the
    pin, and `cove ade status` surfaces any drift from the wheel's default.
    """
    env_path = _compose_env_path()
    line = f"{key}={value}"
    lines = []
    if env_path.exists():
        for existing in env_path.read_text().splitlines():
            if existing.startswith(f"{key}="):
                continue
            lines.append(existing)
    lines.append(line)
    env_path.write_text("\n".join(lines) + "\n")
    env_path.chmod(0o600)


def _running_image() -> str | None:
    """The image the running (or created) ade container was built from,
    e.g. 'cove-ade:0.44.0'. None if the container does not exist."""
    result = subprocess.run(
        ["docker", "inspect", "-f", "{{.Config.Image}}", _container_name()],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode != 0:
        return None
    image = result.stdout.strip()
    return image or None


def _running_version() -> str | None:
    """The bb-app version of the running container, parsed from its image tag."""
    image = _running_image()
    if not image or ":" not in image:
        return None
    return image.rsplit(":", 1)[1]


def _npm_latest_version() -> str:
    """Latest published bb-app version (npm registry JSON API — no npm CLI
    needed on the host)."""
    try:
        resp = requests.get(NPM_LATEST_URL, timeout=15)
        resp.raise_for_status()
        return resp.json()["version"]
    except (requests.RequestException, KeyError, ValueError) as exc:
        raise click.ClickException(
            f"Could not determine the latest bb-app version from npm: {exc}. "
            "Pass an explicit pin: cove ade update --version X.Y.Z"
        ) from exc


def _wait_healthy(timeout_s: int | None = None, poll_s: float | None = None) -> bool:
    deadline = time.monotonic() + (timeout_s if timeout_s is not None else HEALTH_WAIT_S)
    interval = poll_s if poll_s is not None else HEALTH_POLL_S
    while time.monotonic() < deadline:
        for host in ("ade.cove.local", "ade.cove"):
            try:
                health = subprocess.run(
                    ["curl", "-sf", "-H", f"Host: {host}",
                     f"https://127.0.0.1:{NGINX_HTTPS_PORT}/health"],
                    capture_output=True, timeout=10,
                )
            except subprocess.TimeoutExpired:
                continue
            if health.returncode == 0:
                return True
        time.sleep(interval)
    return False


HEALTH_WAIT_S = 90
HEALTH_POLL_S = 3.0


ADE_IMAGE_DEFAULT = "cove-ade:0.44.0"


def _image_prefix() -> str:
    """Preserve the deployed image name prefix (staging uses cove-ade-staging)."""
    image = _read_env_key("ADE_IMAGE") or ADE_IMAGE_DEFAULT
    return image.rsplit(":", 1)[0] if ":" in image else image


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


@ade.command("update")
@click.option("--version", "version_", default=None,
              help="Pin a specific bb-app version (default: latest on npm).")
@click.option("--check", is_flag=True,
              help="Report versions only; change nothing.")
def update(version_: str | None, check: bool):
    """Update the ADE bb server to a new pinned bb-app version.

    Rebuilds the image with the new pin and recreates the container; data
    (the /data volume) is untouched. The previous image tag remains locally,
    so rollback is `cove ade update --version <old>`. Enrolled machines and
    the desktop app follow the server (it serves its own bb-app tarball and
    daemons self-update to the server's protocol) — update the server first,
    then let clients catch up.
    """
    running = _running_version()
    pinned = _read_env_key("ADE_BB_APP_VERSION")
    target = version_.strip() if version_ else _npm_latest_version()
    if not _VERSION_RE.match(target):
        raise click.ClickException(
            f"Invalid bb-app version {target!r} (expected X.Y.Z)."
        )

    if check:
        click.echo(f"  running:  {running or 'container absent'}")
        click.echo(f"  .env pin: {pinned or '(wheel default)'}")
        click.echo(f"  latest:   {target if version_ is None else '(explicit pin) ' + target}")
        return

    if target == running:
        # Running already matches the target: converge the .env pin (it may
        # have lagged — e.g. an update that was interrupted before upsert) and
        # skip the rebuild entirely.
        _upsert_env("ADE_BB_APP_VERSION", target)
        _upsert_env("ADE_IMAGE", f"{_image_prefix()}:{target}")
        click.echo(f"ADE bb server is already at bb-app {target} (pin reconciled).")
        return

    old_image = _read_env_key("ADE_IMAGE")
    old_pin = pinned
    prefix = _image_prefix()
    click.echo(f"Updating ADE bb server: {running or '(absent)'} -> {target}...")
    _upsert_env("ADE_BB_APP_VERSION", target)
    _upsert_env("ADE_IMAGE", f"{prefix}:{target}")

    _run_checked(_compose_cmd("up", "-d", "--build", ADE_SERVICE), "up")

    if _wait_healthy():
        click.echo(f"ADE bb server updated to bb-app {target} at {ADE_URL}")
        click.echo(
            "Enrolled machines follow the server (tarball + protocol "
            "self-update); let the desktop app update to match."
        )
        return

    # Health never converged — roll back to the previous pin (the old image
    # tag still exists locally; version-tagged images make rollback cheap).
    click.echo("Update did not become healthy — rolling back.", err=True)
    if old_image:
        _upsert_env("ADE_IMAGE", old_image)
    else:
        _upsert_env("ADE_IMAGE", f"{prefix}:{target}")  # keep; container absent before
    if old_pin:
        _upsert_env("ADE_BB_APP_VERSION", old_pin)
    _run_checked(_compose_cmd("up", "-d", ADE_SERVICE), "up")
    raise click.ClickException(
        f"Update to bb-app {target} failed the health check; rolled back to "
        f"{old_pin or running or 'previous state'}. Check `cove ade logs` and "
        "the bb-app release notes for breaking changes."
    )


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
                ["curl", "-sf", "-H", f"Host: {host}", f"https://127.0.0.1:{NGINX_HTTPS_PORT}/health"],
                capture_output=True, text=True, timeout=10,
            )
        except subprocess.TimeoutExpired:
            continue
        if health.returncode == 0:
            click.echo("  Health: OK")
            running = _running_version()
            pinned = _read_env_key("ADE_BB_APP_VERSION")
            if running:
                click.echo(f"  bb-app: {running}")
                if pinned and pinned != running:
                    click.echo(
                        f"  NOTE: .env pins bb-app {pinned} but the container runs "
                        f"{running} — run `cove ade up` (or `cove ade update`) to converge."
                    )
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
