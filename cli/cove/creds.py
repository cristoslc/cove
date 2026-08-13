"""CLI commands for credential lifecycle management."""

import os
import platform
import socket
import stat
import sys
import tempfile
from pathlib import Path

import click

from cove import op_bulk_write, vault_cache


OP_REFS = {
    "forgejo_admin": "op://Private/Forgejo {hostname} Admin/password",
    "vault_user": "op://Private/Vault {hostname} {username}/password",
    "minio_root": "op://Private/MinIO {hostname} Root/password",
    # Shared (non-hostname) items — ADR-017 unified Cove admin identity and the
    # Speedtest Tracker APP_KEY. These have no {hostname}/{username} placeholders,
    # so .format() is a no-op. Pulled by batch-pull so `cove speedtest up` can
    # resolve the admin identity + APP_KEY on a fresh machine.
    "cove_admin_username": "op://Private/Cove Admin/username",
    "cove_admin_password": "op://Private/Cove Admin/password",
    "speedtest_app_key": "op://Private/Speedtest Tracker/app_key",
}

HOSTNAME = platform.node().split(".")[0]
USERNAME = os.environ.get("USER", "")


@click.group()
def creds():
    """Manage credentials.

    Examples:

        cove creds vault-get 'op://Private/My Secret/password'

        cove creds vault-put 'op://Private/My Secret/password'

        cove creds batch-pull

        cove creds 1p-bulk-write spec.yml

        cove creds 1p-bulk-write spec.yml --execute
    """


@creds.command("vault-put")
@click.argument("op_ref")
@click.option(
    "--force-refresh",
    is_flag=True,
    help="Bypass Vault cache and re-fetch from 1Password.",
)
def vault_put(op_ref: str, force_refresh: bool):
    """Cache an op:// reference in Vault and emit the resolved value.

    Examples:

        cove creds vault-put 'op://Private/Forgejo MacBook Admin/password'

        cove creds vault-put 'op://Private/My Secret/password' --force-refresh
    """
    try:
        value = vault_cache.vault_put_op_ref(op_ref, force_refresh=force_refresh)
    except (ValueError, RuntimeError) as e:
        raise click.ClickException(str(e))
    sys.stdout.write(value)


@creds.command("vault-get")
@click.argument("op_ref")
def vault_get(op_ref: str):
    """Read a cached op:// reference. Checks local cache first, then Vault.

    Examples:

        cove creds vault-get 'op://Private/Forgejo MacBook Admin/password'

        cove creds vault-get 'op://Private/Vault MacBook user/password'
    """
    from cove import local_cache as lc

    value = lc.get(op_ref)
    if value is not None:
        sys.stdout.write(value)
        return
    try:
        value = vault_cache.vault_get_cached(op_ref)
    except (ValueError, RuntimeError) as e:
        raise click.ClickException(str(e))
    if value is not None:
        lc.put(op_ref, value)
        sys.stdout.write(value)
        return
    raise click.ClickException(
        f"{op_ref} is not cached. Run `cove creds batch-pull` first."
    )


@creds.command("1p-bulk-write")
@click.argument("spec", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--execute",
    is_flag=True,
    help="Run the generated script immediately (one biometric prompt).",
)
def one_password_bulk_write(spec: Path, execute: bool):
    """Generate a self-deleting script that creates 1Password items.

    The SPEC argument is a YAML file with this format:

    \b
        items:
          - title: My App
            vault: Private
            category: login
            fields:
              username: admin
              password: "{{generate:32}}"
              ssh-key[concealed]: "{{file:~/.ssh/id_ed25519}}"

    Field values can be literals, {{generate:N}} (random password of N
    chars, min 4), or {{file:path}} (read file contents).

    Examples:

    \b
        cove creds 1p-bulk-write spec.yml
        cove creds 1p-bulk-write spec.yml --execute
        cove creds 1p-bulk-write ~/projects/cove/secrets/1p-items.yml
    """
    script, plan = op_bulk_write.render_script(spec)

    click.echo("Plan:")
    for line in plan:
        click.echo(line)

    fd, path_str = tempfile.mkstemp(prefix="cove-creds-1p-bulk-", suffix=".sh")
    path = Path(path_str)
    with os.fdopen(fd, "w") as f:
        f.write(script)
    path.chmod(stat.S_IRWXU)

    click.echo(f"\nScript written: {path}")
    if not execute:
        click.echo("Run when ready (it will self-delete on success):")
        click.echo(f"  bash {path}")
        return

    click.echo("Executing (one biometric prompt for the whole batch)…\n")
    import subprocess

    result = subprocess.run(
        ["op", "run", "--", "bash", str(path)], stdin=subprocess.DEVNULL
    )
    if result.returncode != 0:
        try:
            path.unlink()
        except OSError:
            pass
        raise click.ClickException(
            f"Script exited with rc={result.returncode}; deleted"
        )


@creds.command("batch-pull")
@click.option(
    "--force-refresh",
    is_flag=True,
    help="Ignore local cache and re-fetch from 1Password.",
)
def batch_pull_op(force_refresh: bool):
    """Pull all known op:// refs in one batch (single biometric prompt).

    Examples:

        cove creds batch-pull

        cove creds batch-pull --force-refresh
    """
    from cove import local_cache as lc

    if not force_refresh:
        cached = 0
        for ref_template in OP_REFS.values():
            ref = ref_template.format(hostname=HOSTNAME, username=USERNAME)
            if lc.get(ref) is not None:
                cached += 1
        if cached == len(OP_REFS):
            click.echo("All refs already in local cache. Use --force-refresh to repull.")
            return

    refs = [t.format(hostname=HOSTNAME, username=USERNAME) for t in OP_REFS.values()]
    try:
        result = lc.batch_pull(refs)
    except RuntimeError as e:
        raise click.ClickException(str(e))

    for ref, value in result.items():
        click.echo(f"  {ref}: {'*' * 16}")
    click.echo(f"Pulled {len(result)} reference(s) into local cache.")
