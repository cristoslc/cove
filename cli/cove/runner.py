"""CLI commands for Forgejo Actions Runner lifecycle."""

import subprocess

import click

from cove.stateless import resolve_compose_dir


def _compose_dir():
    return resolve_compose_dir()


def _compose_env_path():
    return _compose_dir() / ".env"


def _upsert_env(key: str, value: str) -> None:
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


def _compose_cmd(*args: str) -> list[str]:
    compose_dir = resolve_compose_dir()
    return [
        "docker", "compose",
        "--project-directory", str(compose_dir),
        *args,
    ]


@click.group()
def runner():
    """Manage the Forgejo Actions Runner (optional CI runner).

    The runner polls Forgejo for Actions workflows and executes them
    in Docker containers. It has no ingress route (nginx not required)
    and no admin identity in 1Password.

    Registration is handled by provision_forgejo.yml (IaC) on `cove up`
    when the runner profile is active.
    """


@runner.command()
def up():
    """Start the Forgejo Actions Runner service."""
    click.echo("Starting Forgejo Actions Runner...")
    subprocess.run(_compose_cmd("--profile", "runner", "up", "-d"), check=True)
    click.echo("Forgejo Actions Runner is running.")
    click.echo("Registration is IaC: re-run `cove up` (with runner profile) to register.")


@runner.command()
def down():
    """Stop the Forgejo Actions Runner service (data preserved)."""
    click.echo("Stopping Forgejo Actions Runner...")
    subprocess.run(_compose_cmd("stop", "forgejo-runner"), check=True)
    click.echo("Forgejo Actions Runner stopped.")


@runner.command()
def status():
    """Check Forgejo Actions Runner health."""
    result = subprocess.run(
        _compose_cmd("ps", "--format", "table {{.Name}}\t{{.Status}}\t{{.Ports}}"),
        capture_output=True, text=True,
    )
    click.echo(result.stdout)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


@runner.command()
@click.option("-n", "--lines", default=50, help="Number of lines to show.")
@click.option("-f", "--follow", is_flag=True, help="Follow log output.")
def logs(lines, follow):
    """Tail Forgejo Actions Runner logs."""
    cmd = _compose_cmd("logs", "--tail", str(lines))
    if follow:
        cmd.append("--follow")
    subprocess.run(cmd, check=True)