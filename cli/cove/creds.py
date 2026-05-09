"""CLI commands for credential lifecycle management."""

import os
import stat
import sys
import tempfile
from pathlib import Path

import click

from cove import op_bulk_write, vault_cache


@click.group()
def creds():
    """Manage credentials."""


@creds.command("vault-put")
@click.argument("op_ref")
@click.option(
    "--force-refresh",
    is_flag=True,
    help="Bypass Vault cache and re-fetch from 1Password.",
)
def vault_put(op_ref: str, force_refresh: bool):
    """Cache an op:// reference in Vault and emit the resolved value."""
    try:
        value = vault_cache.vault_put_op_ref(op_ref, force_refresh=force_refresh)
    except (ValueError, RuntimeError) as e:
        raise click.ClickException(str(e))
    sys.stdout.write(value)


@creds.command("vault-get")
@click.argument("op_ref")
def vault_get(op_ref: str):
    """Read a cached op:// reference from Vault."""
    try:
        value = vault_cache.vault_get_cached(op_ref)
    except (ValueError, RuntimeError) as e:
        raise click.ClickException(str(e))
    if value is None:
        raise click.ClickException(
            f"{op_ref} is not cached in Vault. Run `cove creds vault-put {op_ref}` first."
        )
    sys.stdout.write(value)


@creds.command("1p-bulk-write")
@click.argument("spec", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--execute",
    is_flag=True,
    help="Run the generated script immediately (one biometric prompt).",
)
def one_password_bulk_write(spec: Path, execute: bool):
    """Generate a self-deleting script that creates 1Password items."""
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
