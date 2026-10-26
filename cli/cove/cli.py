"""Click entrypoint and group registration."""

import getpass
import sys
import os
import platform
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import click

from cove import __version__
from cove.certs import ca_path, ensure_ca, root_ca_pem, sign_cert
from cove.creds import creds
from cove.ade import ade
from cove.litellm import litellm
from cove.speedtest import speedtest
from cove.runner import runner
from cove.tunnel import tunnel
from cove.toolhive import toolhive
from cove.serve import serve
from cove.sudoers import sudo, passwordless_sudo_ok
from cove.vault import UNSEAL_HINT, vault
from cove.project import (
    _inject, _strip, _container_env, _render_context, _render_guidance,
    _render_agents_block, _write_detail_cove, _write_fj_detail, _write_gh_detail,
    _write_project_override,
    _remove_detail_cove, _remove_project_override,
)
from cove.stateless import (
    resolve_compose_dir, extract_resources, ensure_init, maybe_reextract,
    changed_resource_files, compose_resource_dir, bundle_is_current,
    ensure_compose_source_ready,
)
from cove.constants import VAULT_CONTAINER_NAME
from cove.vault_unseal import ensure_unsealed, vault_health
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


def _running_compose_containers() -> list[str]:
    """Names of running containers in the deployed Cove compose project."""
    result = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}"],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode != 0:
        return []
    return [n for n in result.stdout.split() if n.startswith("cove-")]


def _container_bind_sources(container: str) -> list[Path]:
    """Host source paths of a container's bind mounts (read-only inspect)."""
    result = subprocess.run(
        ["docker", "inspect", container, "--format", "{{range .Mounts}}{{.Source}}\n{{end}}"],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode != 0:
        return []
    return [Path(line) for line in result.stdout.splitlines() if line.strip()]


def _restart_stale_bind_containers(compose_dir: Path, rebuilt: frozenset[str]) -> list[str]:
    """Restart running Cove containers whose bind sources extraction replaced.

    Extraction replaces a bind-mounted file only when its content (or mode)
    changed; a container holding the old unlinked inode serves stale content
    (e.g. nginx 404ing /landing.html) until it restarts. Restart ONLY the
    containers that bind a replaced file: a whole-stack restart would blip
    healthy services for no reason.

    Returns the restarted container names so the caller can heal services whose
    restart has a side effect (Vault starts sealed)."""
    if not rebuilt:
        return []
    rebuilt_abs = {(compose_dir / rel).resolve() for rel in rebuilt}
    restarted: list[str] = []
    for container in _running_compose_containers():
        sources = {p.resolve() for p in _container_bind_sources(container)}
        if not (sources & rebuilt_abs):
            continue
        subprocess.run(
            ["docker", "restart", container],
            capture_output=True, text=True, timeout=120, check=False,
        )
        restarted.append(container)
        click.echo(f"  restarted {container} (rebuilt bind-mounted files)")
    return restarted


# Bounded health probe for the post-restart Vault heal: at most this many
# attempts, this many seconds apart, each request capped at this timeout —
# so `cove up` can never hang waiting on a Vault that never comes up.
# The window must outlast a normal Vault boot: a freshly recreated container
# takes tens of seconds to answer /v1/sys/health (2026-10-22: a 5x1.0s window
# expired first and the heal warned "may still be sealed" on a Vault that was
# simply still starting). attempts x interval now spans ~30s of coverage;
# the loop still returns the moment Vault answers, so a healthy Vault costs
# one probe.
_VAULT_HEALTH_ATTEMPTS = 15
_VAULT_HEALTH_RETRY_SECONDS = 2.0
_VAULT_HEALTH_TIMEOUT_SECONDS = 2.0


def _vault_runtime_state() -> tuple[str, str] | None:
    """(container Id, State.StartedAt) of the Vault container, or None when
    it cannot be read (docker unreachable, container absent)."""
    result = subprocess.run(
        ["docker", "inspect", VAULT_CONTAINER_NAME,
         "--format", "{{.Id}} {{.State.StartedAt}}"],
        capture_output=True, text=True, timeout=15, check=False,
    )
    if result.returncode != 0:
        return None
    parts = result.stdout.strip().split(None, 1)
    return (parts[0], parts[1]) if len(parts) == 2 else None


def _vault_restarted_since(before: tuple[str, str] | None) -> bool:
    """True when the Vault container is now running under an identity that
    differs from the pre-up snapshot: a changed Id is a compose recreate, a
    changed StartedAt on the same Id is a restart (docker restart keeps the
    Id). Covers recreates and restarts driven by the compose invocation
    itself and by bringup handlers — neither is visible to the CLI's
    stale-bind restart list. An unreadable post-up state (docker gone,
    container removed) is left to the end-of-up status gate, which reports
    Vault API failed."""
    after = _vault_runtime_state()
    if after is None:
        return False
    return before is None or before != after


def _unseal_restarted_vault(*, no_provision: bool) -> None:
    """Unseal Vault after this `cove up` (re)started its container.

    A (re)started Vault comes up SEALED — whether the CLI restarted it for a
    changed vault.hcl, the compose run recreated it for a rotated credential
    or a bundle change, or a bringup handler restarted it. The health probe
    is bounded (no unattended hangs). Semantics:
    - reachable + sealed: unseal from the OS keystore via ensure_unsealed();
      a failure prints a non-fatal WARNING telling the operator to run
      `cove vault unseal` (operator decision 2026-10-22, amending the
      PR #79/#83 fail-loud semantics: a failed unseal must not abort the rest
      of `cove up`). The end-of-up status gate still reports Vault API failed.
    - unreachable after the bounded retries: warn clearly and continue — the
      end-of-up status gate reports Vault API failed and `up` exits 1, and
      in the provisioned flow bootstrap_vault.yml retries health for up to
      60s and unseals itself; failing the heal here would abort before both.
    - not initialized: skip (bootstrap_vault.yml initializes and unseals);
      with --no-provision warn that nothing will bootstrap it."""
    health = None
    for attempt in range(_VAULT_HEALTH_ATTEMPTS):
        try:
            health = vault_health(timeout=_VAULT_HEALTH_TIMEOUT_SECONDS)
            break
        # RuntimeError: vault_health's "unreachable". OSError: transport
        # failures a request timeout surfaces directly (read timeout,
        # SSL). ValueError: a response that is not health JSON. All mean
        # "not answering yet" — retry within the bound.
        except (RuntimeError, OSError, ValueError):
            if attempt < _VAULT_HEALTH_ATTEMPTS - 1:
                time.sleep(_VAULT_HEALTH_RETRY_SECONDS)
    if health is None:
        click.echo(
            f"WARNING: {VAULT_CONTAINER_NAME} was (re)started by this `cove up` "
            "but did not answer its health endpoint; it may still be sealed. "
            "Check `cove status`.", err=True)
        return
    if not health.get("initialized", False):
        if no_provision:
            click.echo(
                "WARNING: Vault is not initialized and `--no-provision` skips "
                "bootstrap_vault.yml, so it will stay sealed. Run `cove up` "
                "(with provisioning) to bootstrap it.", err=True)
        return
    if not health.get("sealed", False):
        return
    try:
        ensure_unsealed()
    except RuntimeError as exc:
        # Non-fatal by operator decision 2026-10-22 (amends the PR #79/#83
        # fail-loud semantics): a failed unseal must not end the run and skip
        # provisioning. The status gate below still reports Vault API failed,
        # so the failure stays visible.
        click.echo(
            "WARNING: Vault was (re)started by this `cove up` and could not be "
            f"unsealed automatically: {exc}. {UNSEAL_HINT}",
            err=True,
        )
        return
    click.echo("Vault unsealed from the OS keystore.")


def _start_optional_services() -> None:
    """Start the optional services whose containers need credentials prepared
    by the CLI first (LiteLLM proxy + Headroom, Speedtest Tracker: 1Password/
    Vault seeds injected into the compose .env before `docker compose up`).
    Runner has no credential step: the bringup playbook starts it via its
    COMPOSE_PROFILES env (ADE is core since 0.8.0; ToolHive likewise has no
    credential step in phase 1 and joins the bringup profiles).

    A failure on one service is reported but does not abort `cove up` —
    optional services stay optional (same contract as `cove status`)."""
    for group, label in ((litellm, "litellm"), (speedtest, "speedtest")):
        cmd = group.commands.get("up")
        if cmd is None or cmd.callback is None:
            continue
        try:
            cmd.callback()
        except click.ClickException as exc:
            click.echo(f"{label} not started: {exc.format_message()}", err=True)
            click.echo(f"Retry with: `cove {label} up`", err=True)
        except subprocess.CalledProcessError:
            click.echo(f"{label} not started (docker compose failed).", err=True)
            click.echo(f"Retry with: `cove {label} up`", err=True)


@click.group(invoke_without_command=True)
@click.version_option(version=__version__, prog_name="cove")
@click.option("--sbom", is_flag=True, help="Print the pinned-artifact inventory (SBOM pin matrix) and exit.")
@click.pass_context
def app(ctx, sbom):
    """Cove management CLI.

    Examples:

        cove init

        cove up

        cove down --volumes

        cove --sbom
    """
    if ctx.invoked_subcommand is not None:
        return
    if sbom:
        from cove.pins import all_pins
        from cove.stateless import resolve_compose_dir

        pins = all_pins(resolve_compose_dir())
        for pin in pins:
            click.echo(f"{pin.name}\t{pin.kind}\t{pin.classified}\t{pin.ref}")
        click.echo(f"\n{len(pins)} pins. CycloneDX snapshots: sbom/ in the repo checkout (generated by scripts/sbom.sh at bump time).")
        return
    click.echo(ctx.get_help())


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


def _report_ansible_failure(playbook: Path, lines: list[str], logfile: Path) -> None:
    """Print a readable failure report for a failed ansible-playbook run.

    Extracts the failing task's origin (playbook:line) and its error message
    from the captured output, then points at the full log file. Fall back to
    the last lines of output when the expected Ansible markers are missing.
    """
    origin = ""
    msg = ""
    for line in lines:
        if line.startswith("Origin: "):
            origin = line[len("Origin: "):].strip()
        m = re.search(r'"msg": "(.+?)", "', line)
        if m:
            msg = m.group(1).replace('\\"', '"').replace("\\n", "\n")
    task_name = ""
    for line in lines:
        m = re.match(r"failed: \[[^\]]+\] \(item=(.*)\)", line.strip())
        if m:
            task_name = m.group(1)
            break
    click.echo(click.style("\n✗ Ansible play failed: ", fg="red", bold=True) + playbook.name, err=True)
    if task_name:
        click.echo(f"  Item:    {task_name}", err=True)
    if origin:
        click.echo(f"  Origin:  {origin}", err=True)
    if msg:
        click.echo("  Problem:", err=True)
        for out_line in msg.splitlines():
            click.echo(f"    {out_line}", err=True)
        if "rm -rf" in msg:
            click.echo("  Fix: re-run the suggested command, then `cove up`.", err=True)
    if not (task_name or origin or msg):
        # Unrecognized failure shape: show the tail of the raw output.
        click.echo("  Last output:", err=True)
        for out_line in lines[-15:]:
            click.echo(f"    {out_line.rstrip()}", err=True)
    click.echo(f"  Full log: {logfile}", err=True)


@app.command()
@click.option("--no-provision", is_flag=True, help="Skip Forgejo provisioning")
@click.option("--no-upgrade", is_flag=True, help="Skip version-based re-extraction of compose resources.")
@click.option("--all", "all_", is_flag=True, help="Also start all optional services (LiteLLM + Headroom, Runner, Speedtest). The tunnel is excluded: shares are created interactively with `cove tunnel up`.")
@click.option("--log", is_flag=True, help="Write ansible output to ~/.local/share/cove/logs/")
@click.option("--non-interactive", is_flag=True,
              help="No prompts (scheduled runs): skip the BECOME prompt; elevation "
                   "tasks are idempotent no-ops on established machines.")
def up(no_provision, no_upgrade, all_, log, non_interactive=False):
    """Bring up cove containers and provision Forgejo.

    Compose dir is resolved in order: COVE_COMPOSE_DIR env, ./compose,
    .worktrees/<name>/compose, git-toplevel/compose, ~/.config/cove/compose.

    Examples:

        cove up

        cove up --no-provision

        cove up --all

        cove up --log
    """
    # Re-extraction only changes an inode for a file whose CONTENT changed
    # (unchanged files are overwritten in place). Those are the only files that
    # can leave a running container with a stale, unlinked bind, so only they
    # may trigger a restart (2026-10-19 stale-inode sev-2).
    changed = changed_resource_files() if not bundle_is_current() else frozenset()
    if not no_upgrade:
        maybe_reextract()
    ensure_init()
    compose_dir = resolve_compose_dir()
    # Refuse a compose source that would collapse every ${COVE_DATA_ROOT}/x bind
    # to container-absolute /x, or hijack the live project from a foreign data
    # root. Runs before Ansible and before any container is touched.
    ensure_compose_source_ready(compose_dir)
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
        # Always capture the stream so a failure can produce a readable
        # report instead of Ansible's raw fatal dump at the bottom of the
        # terminal (and so failure logs always exist for debugging).
        ansible_env["ANSIBLE_NOCOLOR"] = "1"
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        logfile = (log_dir or Path.home() / ".local" / "share" / "cove" / "logs") / f"{ts}-{playbook.name}.log"
        if log:
            click.echo(f"  log: {logfile}")
        logfile.parent.mkdir(parents=True, exist_ok=True)
        lines: list[str] = []
        with open(logfile, "w") as f:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=ansible_env)
            for line in proc.stdout or []:
                click.echo(line, nl=False)
                lines.append(line)
                f.write(line)
            proc.wait()
        result = proc
        if result.returncode != 0:
            _report_ansible_failure(playbook, lines, logfile)
            raise SystemExit(result.returncode)

    base_cmd = ["ansible-playbook", "-i", str(inventory)]
    base_cmd.extend(["-e", f"@{host_vars_file}"])
    # Ansible gathers ansible_hostname from the kernel hostname, which on macOS
    # drifts to the DHCP-assigned name when HostName is unset (e.g. 'Mac'). The
    # CLI keys everything else (cert SANs, host_vars, 1Password op_refs) on the
    # stable LocalHostName, so override the fact to keep Ansible consistent.
    base_cmd.extend(["-e", f"ansible_hostname={host_vars_file.stem}"])

    # Prompt for the BECOME password only when the operator has not installed
    # the passwordless sudoers drop-in (`cove sudo enable`). Scheduled runs
    # (`cove update --quiet` → `cove up --non-interactive`) have no TTY and no
    # password: they skip the prompt, and the become-requiring bringup tasks
    # (e.g. /etc/hosts) are idempotent no-ops on established machines and
    # tolerate failure.
    if non_interactive or passwordless_sudo_ok():
        ansible_env["ANSIBLE_BECOME_PASS"] = ""
    else:
        become_pass = getpass.getpass("BECOME password: ")
        ansible_env["ANSIBLE_BECOME_PASS"] = become_pass

    # `cove up --all` starts every optional service. LiteLLM and Speedtest
    # need credentials prepared by the CLI (1Password/Vault seeds injected
    # into the compose .env) BEFORE their containers start, so their profiles
    # stay out of the bringup compose up and their `up` flows run after the
    # provisioning chain (Vault must be up for the vault-get/vault-put calls).
    # Runner has no such step: the bringup starts it via its COMPOSE_PROFILES
    # env (ADE is core since 0.8.0 — the bringup starts it unconditionally).
    # ToolHive is the same: no credential step in phase 1 (per-server secrets
    # are Phase 2), so its profile joins the bringup like the runner's.
    # Running optionals are still reconciled by the bringup (their .env
    # credentials already exist).
    bringup_profiles = ["runner", "mcp"] if all_ else []
    for profile in _detect_running_optional_profiles():
        if profile not in bringup_profiles:
            bringup_profiles.append(profile)
    if bringup_profiles:
        base_cmd.extend(["-e", f"cove_profiles={','.join(bringup_profiles)}"])
    # Scheduled updates force re-pull so floating tags (forgejo:15, nginx)
    # actually receive new upstream patches instead of freezing at first pull.
    pull_policy = os.environ.pop("COVE_PULL_POLICY", None)
    if pull_policy:
        base_cmd.extend(["-e", f"pod_pull_policy={pull_policy}"])

    if not no_provision:
        click.echo("Pulling credentials from 1Password...")
        subprocess.run(["cove", "creds", "batch-pull"], check=True)

    # Snapshot Vault's runtime identity before the compose run: recreates and
    # restarts driven by the compose invocation itself (rotated credential in
    # the .env, bundle change, bringup handler) are invisible to the
    # stale-bind restart list below, yet they (re)start Vault just as surely
    # (2026-10-20/21: two `cove up` runs left Vault sealed this way).
    vault_before = _vault_runtime_state()
    _run_ansible(bringup, "Bringing up containers...")

    restarted: list[str] = []
    if changed:
        # Re-extraction replaced these files' inodes; restart only the running
        # containers that bind one (bringup's 'Reload nginx' handler covers
        # Ansible-rendered configs, not bundle extraction).
        restarted = _restart_stale_bind_containers(
            compose_resource_dir(), changed
        )
    if not no_provision:
        _run_ansible(compose_dir / "bootstrap_vault.yml", "Bootstrapping Vault...")
        _run_ansible(compose_dir / "provision_vault_user.yml", "Provisioning Vault user...")
        _run_ansible(provision, "Provisioning Forgejo...")

    if all_:
        _start_optional_services()
        click.echo(
            "Tunnel not included: shares are created interactively with `cove tunnel up`."
        )

    # Unseal is the LAST converge step (operator decision 2026-10-22). It runs
    # after provisioning so a failed unseal cannot skip provisioning, and it is
    # the only heal the `--no-provision` path (`cove update`, `cove serve run`)
    # gets — bootstrap_vault.yml never runs there.
    if VAULT_CONTAINER_NAME in restarted or _vault_restarted_since(vault_before):
        _unseal_restarted_vault(no_provision=no_provision)

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
    if sign_cert(list(sans), key_file, cert_file):
        click.echo(f"Signed: {cert_file}")
    else:
        click.echo(f"Up-to-date: {cert_file}")


app.add_command(creds)
app.add_command(ade)
app.add_command(litellm)
app.add_command(speedtest)
app.add_command(runner)
app.add_command(tunnel)
app.add_command(toolhive)
app.add_command(sudo)
app.add_command(serve)
app.add_command(vault)
from cove.update import update

app.add_command(update)


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
    ensure_compose_source_ready(compose_dir)
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
        ensure_compose_source_ready(compose_dir)
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
