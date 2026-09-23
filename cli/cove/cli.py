"""Click entrypoint and group registration."""

import getpass
import os
import platform
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import click

from cove import __version__
from cove.certs import ca_path, ensure_ca, root_ca_pem, sign_cert
from cove.creds import creds
from cove.litellm import litellm
from cove.speedtest import speedtest
from cove.runner import runner
from cove.tunnel import tunnel
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


def _detect_running_optional_profiles() -> list[str]:
    """Return the compose profiles of optional services that are currently
    running, so `cove up` can reconcile them (recreate with current config)
    without starting stopped optionals."""
    import json
    from cove.status import OPTIONAL_SERVICES
    result = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}"],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode != 0:
        return []
    running = set(result.stdout.strip().split("\n"))
    profiles = []
    for container_name, _label, profile in OPTIONAL_SERVICES:
        if container_name in running and profile not in profiles:
            profiles.append(profile)
    return profiles


@click.group()
@click.version_option(version=__version__, prog_name="cove")
def app():
    """Cove management CLI.

    Examples:

        cove init

        cove up

        cove down --volumes
    """


@app.command()
@click.option("--force", is_flag=True, help="Re-extract resources even if version matches.")
@click.option("--purge", is_flag=True, help="Remove ~/.config/cove/compose/ entirely.")
def init(force, purge):
    """Extract bundled compose resources to ~/.config/cove/compose/.

    Examples:

        cove init

        cove init --force

        cove init --purge
    """
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
@click.option("--no-upgrade", is_flag=True, help="Skip version-based re-extraction of compose resources.")
@click.option("--log", is_flag=True, help="Write ansible output to ~/.local/share/cove/logs/")
def up(no_provision, no_upgrade, log):
    """Bring up cove containers and provision Forgejo.

    Compose dir is resolved in order: COVE_COMPOSE_DIR env, ./compose,
    .worktrees/<name>/compose, git-toplevel/compose, ~/.config/cove/compose.

    Examples:

        cove up

        cove up --no-provision

        cove up --log
    """
    if not no_upgrade:
        maybe_reextract()
    ensure_init()
    compose_dir = resolve_compose_dir()
    host_vars_file = ensure_host_vars()
    inventory = compose_dir / "inventory.yml"
    bringup = compose_dir / "bringup.yml"
    provision = compose_dir / "provision_forgejo.yml"

    log_dir: Path | None = None
    if log:
        log_dir = Path.home() / ".local" / "share" / "cove" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)

    ansible_env = os.environ.copy()
    ansible_cfg = compose_dir / "ansible.cfg"
    if ansible_cfg.exists():
        ansible_env["ANSIBLE_CONFIG"] = str(ansible_cfg)

    def _run_ansible(playbook, label):
        click.echo(label)
        cmd = base_cmd + [str(playbook)]
        if log:
            assert log_dir is not None
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            logfile = log_dir / f"{ts}-{playbook.name}.log"
            with open(logfile, "w") as f:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=ansible_env)
                for line in proc.stdout or []:
                    click.echo(line, nl=False)
                    f.write(line)
                proc.wait()
                result = proc
            click.echo(f"  log: {logfile}")
        else:
            result = subprocess.run(cmd, env=ansible_env)
        if result.returncode != 0:
            raise SystemExit(result.returncode)

    base_cmd = ["ansible-playbook", "-i", str(inventory)]
    base_cmd.extend(["-e", f"@{host_vars_file}"])
    # Ansible gathers ansible_hostname from the kernel hostname, which on macOS
    # drifts to the DHCP-assigned name when HostName is unset (e.g. 'Mac'). The
    # CLI keys everything else (cert SANs, host_vars, 1Password op_refs) on the
    # stable LocalHostName, so override the fact to keep Ansible consistent.
    base_cmd.extend(["-e", f"ansible_hostname={host_vars_file.stem}"])

    become_pass = getpass.getpass("BECOME password: ")
    ansible_env["ANSIBLE_BECOME_PASSWORD"] = become_pass

    running_profiles = _detect_running_optional_profiles()
    if running_profiles:
        base_cmd.extend(["-e", f"cove_profiles={','.join(running_profiles)}"])

    if not no_provision:
        click.echo("Pulling credentials from 1Password...")
        subprocess.run(["cove", "creds", "batch-pull"], check=True)

    _run_ansible(bringup, "Bringing up containers...")

    if not no_provision:
        _run_ansible(compose_dir / "bootstrap_vault.yml", "Bootstrapping Vault...")
        _run_ansible(compose_dir / "provision_vault_user.yml", "Provisioning Vault user...")
        _run_ansible(provision, "Provisioning Forgejo...")

    from cove.status import check_all, print_status
    results = check_all()
    print_status(results)
    if not all(r.ok or r.optional for r in results):
        raise SystemExit(1)
    click.echo("Cove is up.")


@app.command()
def status():
    """Check health of cove services.

    Verifies containers are running, nginx ingress responds,
    Forgejo and Vault APIs are reachable, and DNS resolves correctly.

    Examples:

        cove status
    """
    from cove.status import check_all, print_status
    results = check_all()
    print_status(results)
    if not all(r.ok or r.optional for r in results):
        raise SystemExit(1)


@app.group()
def certs():
    """Manage TLS certificates."""


@certs.command("ensure-ca")
@click.option("--skip-trust-store", is_flag=True, help="Generate CA files but skip system trust store install.")
def certs_ensure_ca(skip_trust_store):
    """Generate root CA if missing and install to system trust store."""
    if skip_trust_store:
        from cove.certs import _ensure_ca
        _ensure_ca()
    else:
        ensure_ca()
    click.echo(f"Root CA: {ca_path() / 'rootCA.pem'}")


@certs.command("ca-path")
def certs_ca_path():
    """Print the CA directory path."""
    click.echo(ca_path())


@certs.command("root-ca-pem")
def certs_root_ca_pem():
    """Print the root CA certificate in PEM format."""
    click.echo(root_ca_pem(), nl=False)


@certs.command()
@click.option("--sans", multiple=True, required=True, help="Subject Alternative Names (repeatable)")
@click.option("--key-file", required=True, type=click.Path(path_type=Path))
@click.option("--cert-file", required=True, type=click.Path(path_type=Path))
def sign(sans, key_file, cert_file):
    """Generate a TLS certificate signed by the root CA."""
    sign_cert(list(sans), key_file, cert_file)
    click.echo(f"Signed: {cert_file}")


app.add_command(creds)
app.add_command(litellm)
app.add_command(speedtest)
app.add_command(runner)
app.add_command(tunnel)


@app.command()
@click.option("-g", "--global", "global_", is_flag=True, help="Install to ~/.agents/AGENTS.md")
def install(global_):
    """Inject cove service guidance into the project or global Claude config.

    Examples:

        cove install

        cove install --global
    """
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

    Examples:

        cove down

        cove down --volumes
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
@click.option("-a", "--all", "all_", is_flag=True, help="Also stop containers and remove cached credentials (default: guidance only).")
@click.option("-f", "--force", is_flag=True, help="Skip confirmation prompt.")
@click.option("-g", "--global", "global_", is_flag=True, help="Remove from global ~/.agents/AGENTS.md instead of local.")
def uninstall(all_, force, global_):
    """Remove cove agent guidance.

    By default, only strips cove guidance from AGENTS.md and removes spoke docs.
    Containers and credentials are preserved. Use --all to also stop containers
    and remove cached credentials (data in ~/Documents/cove-data/ is always preserved).

    Examples:

        cove uninstall

        cove uninstall --all

        cove uninstall --all --force

        cove uninstall --global
    """
    compose_dir = resolve_compose_dir()

    if all_:
        scope = "guidance + containers + credentials"
    else:
        scope = "guidance only (containers and credentials preserved)"

    if not force:
        click.confirm(
            f"Remove {scope}?",
            abort=True,
        )

    if all_:
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
    """Print the CLI version.

    Examples:

        cove version

        cove --version
    """
    click.echo(f"cove {__version__}")
