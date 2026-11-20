"""CLI commands for the edge secrets check (observe-only).

The scanner sits in front of Bifrost, scans request bodies against the
repository's one `.gitleaks.toml`, logs hits without the matched text, and
forwards every request unchanged. It never blocks. See
docs/services/secrets-guard.md for placement, the measured cost, and how
blocking becomes a later decision.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import click

from cove.credential_env import resolve_data_root, scrubbed_environment
from cove.stateless import ensure_compose_source_ready, resolve_compose_dir

CONTAINER = "secrets-guard"
RULES_NAME = "gitleaks.toml"
DEFAULT_PORT = "4003"
SYNC_HINT = (
    "compose/secrets-guard/gitleaks.toml is missing. It is generated from the "
    "repository's single .gitleaks.toml: run "
    "`python3 cli/scripts/sync_compose_resources.py` (or reinstall cove) and "
    "retry."
)


def _compose_cmd(*args: str) -> list[str]:
    compose_dir = resolve_compose_dir()
    return [
        "docker", "compose",
        "--project-directory", str(compose_dir),
        *args,
    ]


def _seed_rules(compose_dir: Path) -> Path:
    """Publish the bundled ruleset where the container mounts it.

    The source is the wheel's generated copy of the repo's `.gitleaks.toml`
    (the file the commit-hook gate reads). The deployed copy is an artifact,
    rewritten on every `up`, so a rules change in the wheel reaches an existing
    host. Never edit the deployed copy: edit `.gitleaks.toml`.
    """
    source = compose_dir / CONTAINER / RULES_NAME
    if not source.is_file():
        raise click.ClickException(SYNC_HINT)

    data_root = resolve_data_root(compose_dir / ".env")
    target_dir = data_root / CONTAINER
    target_dir.mkdir(mode=0o755, parents=True, exist_ok=True)
    target = target_dir / RULES_NAME
    target.write_bytes(source.read_bytes())
    target.chmod(0o644)
    return target


def _env_value(compose_dir: Path, key: str, default: str) -> str:
    """Literal NAME=VALUE from the compose .env, else the default."""
    env_path = compose_dir / ".env"
    try:
        lines = env_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        return default
    for line in lines:
        if line.startswith(f"{key}="):
            value = line.split("=", 1)[1].strip()
            if value:
                return value
    return default


@click.group()
def secrets_guard():
    """Manage the observe-only secrets check in front of the Bifrost gateway.

    Every request body is scanned against the repository's own gitleaks
    ruleset, hits are logged as JSON lines without the matched text, and every
    request is forwarded to Bifrost unchanged. Nothing is blocked or rewritten;
    blocking is a later decision with its own evidence.

    The service has its own compose profile, so `cove up` and `cove bifrost up`
    never start it. Starting it exposes a loopback port; nothing routes client
    traffic through it until the operator points something at that port.
    """


@secrets_guard.command()
def up():
    """Start the observe-only scanner in front of Bifrost."""
    compose_dir = resolve_compose_dir()
    ensure_compose_source_ready(compose_dir)
    rules = _seed_rules(compose_dir)
    click.echo(f"Rules: {rules} (generated from .gitleaks.toml)")
    click.echo("Starting the edge secrets check (profile: secrets-guard)...")
    subprocess.run(
        _compose_cmd("--profile", "secrets-guard", "up", "-d", "--build"),
        check=True,
        env=scrubbed_environment(compose_dir),
    )
    port = _env_value(compose_dir, "SECRETS_GUARD_PORT", DEFAULT_PORT)
    click.echo(f"Observe-only scanner listening on 127.0.0.1:{port} -> http://bifrost:8080")
    click.echo(
        f"Nothing routes to it yet. Point a client or probe at "
        f"http://127.0.0.1:{port}/v1 with the Bifrost virtual key: every request "
        "is forwarded unchanged, and a rule hit is logged."
    )


@secrets_guard.command()
def down():
    """Stop the observe-only scanner (Bifrost is untouched)."""
    compose_dir = resolve_compose_dir()
    ensure_compose_source_ready(compose_dir)
    click.echo("Stopping the edge secrets check...")
    subprocess.run(
        _compose_cmd("stop", CONTAINER),
        check=True,
        env=scrubbed_environment(compose_dir, warn=False),
    )
    click.echo("Edge secrets check stopped.")


@secrets_guard.command()
def status():
    """Show the scanner's container state and posture."""
    compose_dir = resolve_compose_dir()
    result = subprocess.run(
        _compose_cmd("ps", "--format", "table {{.Name}}\t{{.Status}}\t{{.Ports}}", CONTAINER),
        capture_output=True, text=True,
        env=scrubbed_environment(compose_dir, warn=False),
    )
    click.echo(result.stdout, nl=False)
    if result.returncode != 0:
        raise SystemExit(result.returncode)
    mode = _env_value(compose_dir, "SECRETS_GUARD_LOG", "all")
    port = _env_value(compose_dir, "SECRETS_GUARD_PORT", DEFAULT_PORT)
    click.echo("Mode: observe-only (no request is blocked or altered)")
    click.echo(f"Log mode: {mode}; listen 127.0.0.1:{port} -> http://bifrost:8080")
    click.echo("Read hits with: cove secrets-guard logs")


@secrets_guard.command()
@click.option("-n", "--lines", default=50, help="Number of lines to show.")
@click.option("-f", "--follow", is_flag=True, help="Follow log output.")
def logs(lines, follow):
    """Tail the scanner's JSON log lines."""
    cmd = _compose_cmd("logs", "--tail", str(lines), CONTAINER)
    if follow:
        cmd.append("--follow")
    subprocess.run(
        cmd, check=True, env=scrubbed_environment(resolve_compose_dir(), warn=False)
    )
