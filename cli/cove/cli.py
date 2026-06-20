"""Click entrypoint and group registration."""

import os
import platform
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import click

from cove import __version__
from cove.creds import creds
from cove.project import (
    _inject, _strip, _container_env, _render_context, _render_guidance,
    _render_agents_block, _write_detail_cove, _write_fj_detail, _write_gh_detail,
    _write_project_override,
    _remove_detail_cove, _remove_project_override,
)
from cove.stateless import (
    resolve_compose_dir, extract_resources, ensure_init, maybe_reextract,
)
from cove.state import ensure_host_vars


@click.group()
@click.version_option(version=__version__, prog_name="cove")
def app():
    """Cove management CLI."""


@app.command()
@click.option("--force", is_flag=True, help="Re-extract resources even if version matches.")
@click.option("--purge", is_flag=True, help="Remove ~/.config/cove/compose/ entirely.")
def init(force, purge):
    """Extract bundled compose resources to ~/.config/cove/compose/."""
    if purge:
        target = Path.home() / ".config" / "cove" / "compose"
        if target.exists():
            shutil.rmtree(target)
            click.echo(f"Removed {target}")
        else:
            click.echo(f"Nothing to remove at {target}")
        return
    path = extract_resources(force=force)
    click.echo(f"Compose resources extracted to {path}")
    reqs = path / "requirements.yml"
    if reqs.exists():
        click.echo("Installing Ansible collections...")
        subprocess.run(
            ["ansible-galaxy", "collection", "install", "-r", str(reqs)],
            check=False,
        )
    click.echo(f"cove {__version__} ready. Run `cove up` to bring up services.")


@app.command()
@click.option("--no-provision", is_flag=True, help="Skip Forgejo provisioning")
@click.option("--no-sudo", is_flag=True, help="Skip sudo elevation for /etc/hosts (safe if already configured)")
@click.option("--no-upgrade", is_flag=True, help="Skip version-based re-extraction of compose resources.")
@click.option("--log", is_flag=True, help="Write ansible output to ~/.local/share/cove/logs/")
def up(no_provision, no_sudo, no_upgrade, log):
    """Bring up cove containers and provision Forgejo.

    Compose dir is resolved in order: COVE_COMPOSE_DIR env, ./compose,
    .worktrees/<name>/compose, git-toplevel/compose, ~/.config/cove/compose.
    """
    if not no_upgrade:
        maybe_reextract()
    ensure_init()
    compose_dir = resolve_compose_dir()
    host_vars_file = ensure_host_vars()
    inventory = compose_dir / "inventory.yml"
    bringup = compose_dir / "bringup.yml"
    provision = compose_dir / "provision_forgejo.yml"

    log_dir = None
    if log:
        log_dir = Path.home() / ".local" / "share" / "cove" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)

    def _run_ansible(playbook, label):
        click.echo(label)
        cmd = base_cmd + [str(playbook)]
        if log:
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            logfile = log_dir / f"{ts}-{playbook.name}.log"
            with open(logfile, "w") as f:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                for line in proc.stdout:
                    click.echo(line, nl=False)
                    f.write(line)
                proc.wait()
                result = proc
            click.echo(f"  log: {logfile}")
        else:
            result = subprocess.run(cmd)
        if result.returncode != 0:
            raise SystemExit(result.returncode)

    base_cmd = ["ansible-playbook", "-i", str(inventory)]
    base_cmd.extend(["-e", f"@{host_vars_file}"])
    if not no_sudo:
        base_cmd.append("-K")
    else:
        base_cmd.extend(["-e", "ansible_become=no"])

    if not no_provision:
        click.echo("Pulling credentials from 1Password...")
        subprocess.run(["cove", "creds", "batch-pull"], check=True)

    _run_ansible(bringup, "Bringing up containers...")

    if not no_provision:
        _run_ansible(compose_dir / "bootstrap_vault.yml", "Bootstrapping Vault...")
        _run_ansible(compose_dir / "provision_vault_user.yml", "Provisioning Vault user...")
        _run_ansible(provision, "Provisioning Forgejo...")

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
    _write_fj_detail(detail_path.parent / "fj.md")
    _write_gh_detail(detail_path.parent / "gh.md")
    if override:
        _write_project_override(override, ctx)
    agents_block = _render_agents_block(ctx, detail_ref)
    _inject(target, agents_block)


@app.command()
@click.option("--volumes", is_flag=True, help="Also remove named volumes (destroys container data).")
def down(volumes):
    """Stop cove containers.

    Compose dir resolution: see `cove up --help` (COVE_COMPOSE_DIR env, etc.).
    """
    compose_dir = resolve_compose_dir()
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
@click.option("--yes", is_flag=True, help="Confirm container/data destruction.")
@click.option("-g", "--global", "global_", is_flag=True, help="Remove from global ~/.agents/AGENTS.md instead of local.")
def uninstall(yes, global_):
    """Stop cove containers, remove credentials, and strip agent guidance."""
    compose_dir = resolve_compose_dir()

    if not yes:
        click.confirm(
            "Stop containers and remove credentials? (data in ~/Documents/cove-data/ is preserved)",
            abort=True,
        )

    click.echo("Stopping containers...")
    subprocess.run(
        [
            "docker", "compose",
            "--project-directory", str(compose_dir),
            "down", "--remove-orphans",
        ],
        check=False,
    )

    home = Path.home()
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

    if global_:
        targets = [Path.home() / ".agents" / "AGENTS.md"]
        detail_dir = Path.home() / ".agents" / "agents-md-detail"
    else:
        targets = [Path.cwd() / "AGENTS.md"]
        detail_dir = Path.cwd() / ".agents" / "agents-md-detail"

    for target in targets:
        _strip(target)

    for spoke in ["cove.md", "fj.md", "gh.md"]:
        p = detail_dir / spoke
        if p.exists():
            p.unlink()
            click.echo(f"Removed {p}")

    if detail_dir.exists() and not any(detail_dir.iterdir()):
        detail_dir.rmdir()
        click.echo(f"Removed empty {detail_dir}")

    if not global_:
        _remove_project_override(Path.cwd())

    click.echo("Cove uninstalled.")
    click.echo("To remove the CLI: uv tool uninstall cove-cli")


@app.command()
def version():
    """Print the CLI version."""
    click.echo(f"cove {__version__}")
