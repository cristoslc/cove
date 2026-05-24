"""Click entrypoint and group registration."""

import os
import platform
import shutil
import subprocess
from pathlib import Path

import click

from cove import __version__
from cove.creds import creds
from cove.project import (
    _inject, _strip, _container_env, _render_context, _render_guidance,
    _render_agents_block, _write_detail_cove, _write_project_override,
    _remove_detail_cove, _remove_project_override,
)

def _find_compose_dir() -> Path:
    cwd = Path.cwd()
    for candidate in [cwd / "compose", cwd / ".worktrees" / cwd.name / "compose"]:
        if (candidate / "inventory.yml").exists():
            return candidate
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, cwd=str(cwd),
    )
    if result.returncode == 0:
        git_root = Path(result.stdout.strip())
        if (git_root / "compose" / "inventory.yml").exists():
            return git_root / "compose"
    raise click.ClickException("Could not find compose/inventory.yml. Run from a cove project directory.")


@click.group()
@click.version_option(version=__version__, prog_name="cove")
def app():
    """Cove management CLI."""


@app.command()
@click.option("--no-provision", is_flag=True, help="Skip Forgejo provisioning")
@click.option("--no-sudo", is_flag=True, help="Skip sudo elevation for /etc/hosts (safe if already configured)")
def up(no_provision, no_sudo):
    """Bring up cove containers and provision Forgejo."""
    compose_dir = _find_compose_dir()
    inventory = compose_dir / "inventory.yml"
    bringup = compose_dir / "bringup.yml"
    provision = compose_dir / "provision_forgejo.yml"

    base_cmd = ["ansible-playbook", "-i", str(inventory)]
    if not no_sudo:
        base_cmd.append("-K")
    else:
        base_cmd.extend(["-e", "ansible_become=no"])

    if not no_provision:
        click.echo("Pulling credentials from 1Password...")
        subprocess.run(
            ["cove", "creds", "batch-pull"],
            check=True,
        )

    click.echo("Bringing up containers...")
    subprocess.run(
        base_cmd + [str(bringup)],
        check=True,
    )

    if not no_provision:
        click.echo("Bootstrapping Vault...")
        bootstrap_vault = compose_dir / "bootstrap_vault.yml"
        provision_vault_user = compose_dir / "provision_vault_user.yml"
        for p in [bootstrap_vault, provision_vault_user]:
            subprocess.run(
                base_cmd + [str(p)],
                check=True,
            )

        click.echo("Provisioning Forgejo...")
        subprocess.run(
            base_cmd + [str(provision)],
            check=True,
        )

    click.echo("Cove is up.")


app.add_command(creds)


@app.command()
@click.option("-g", "--global", "global_", is_flag=True, help="Install to ~/.agents/AGENTS.md")
def install(global_):
    """Inject cove service guidance into the project or global Claude config."""
    forgejo = _container_env("cove-forgejo")
    vault = _container_env("cove-vault")
    ctx = _render_context(forgejo, vault)
    rendered = _render_guidance(forgejo, vault)

    if global_:
        target = Path.home() / ".agents" / "AGENTS.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        detail_path = Path.home() / ".agents" / "agents-md-detail" / "cove.md"
        detail_ref = "~/.agents/agents-md-detail/cove.md"
        override = None
    else:
        target = Path.cwd() / "AGENTS.md"
        detail_path = Path.cwd() / ".agents" / "agents-md-detail" / "cove.md"
        detail_ref = ".agents/agents-md-detail/cove.md"
        override = Path.cwd()

    _write_detail_cove(detail_path, rendered)
    if override:
        _write_project_override(override, ctx)
    agents_block = _render_agents_block(ctx, detail_ref)
    _inject(target, agents_block)


@app.command()
@click.option("--volumes", is_flag=True, help="Also remove named volumes (destroys container data).")
def down(volumes):
    """Stop cove containers."""
    compose_dir = _find_compose_dir()
    cmd = [
        "docker", "compose",
        "--project-directory", str(compose_dir),
        "down",
    ]
    if volumes:
        cmd.append("--volumes")

    click.echo("Stopping containers...")
    subprocess.run(cmd, check=True)
    click.echo("Cove is down.")


@app.command()
@click.option("--yes", is_flag=True, help="Confirm destruction of all cove data.")
def uninstall(yes):
    """Destroy all cove containers, data, and credentials."""
    if not yes:
        raise click.ClickException(
            "This will destroy all cove containers, data, and credentials.\n"
            "Run again with --yes to confirm."
        )

    compose_dir = _find_compose_dir()

    click.echo("Destroying containers and volumes...")
    subprocess.run(
        [
            "docker", "compose",
            "--project-directory", str(compose_dir),
            "down", "--volumes", "--remove-orphans",
        ],
        check=True,
    )

    home = Path.home()
    data_dir = home / "Documents" / "cove-data"
    if data_dir.exists():
        click.echo(f"Removing {data_dir}...")
        shutil.rmtree(str(data_dir))

    cache_dir = Path(os.environ.get("XDG_CACHE_HOME", home / ".cache")) / "cove"
    if cache_dir.exists():
        click.echo(f"Removing {cache_dir}...")
        shutil.rmtree(str(cache_dir))

    if platform.system() == "Darwin":
        subprocess.run(
            ["security", "delete-generic-password", "-s", "cove/vault/root-token"],
            capture_output=True,
        )
        for i in range(1, 6):
            subprocess.run(
                ["security", "delete-generic-password", "-s", f"cove/vault/unseal-{i}"],
                capture_output=True,
            )

    for target in [Path.cwd() / "AGENTS.md", Path.home() / ".agents" / "AGENTS.md"]:
        _strip(target)

    for detail in [Path.cwd() / ".agents" / "agents-md-detail" / "cove.md",
                   Path.home() / ".agents" / "agents-md-detail" / "cove.md"]:
        _remove_detail_cove(detail)

    _remove_project_override(Path.cwd())

    click.echo("Cove uninstalled.")
    click.echo("To remove the CLI: uv tool uninstall cove-cli")


@app.command()
def version():
    """Print the CLI version."""
    click.echo(f"cove {__version__}")
