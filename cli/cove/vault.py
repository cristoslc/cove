"""`cove vault` — local Vault lifecycle verbs.

`unseal` wraps `cove.vault_unseal.ensure_unsealed`: read the Shamir unseal keys
from the OS keystore and POST them to Vault. Standalone on purpose — an operator
can unseal without re-running `cove up` (operator decision 2026-10-22; see
docs/musings/cove-serve-autostart.md).
"""

from __future__ import annotations

import click

from cove.vault_unseal import ensure_unsealed

# The single fix-it line every unseal failure points at. Shared so `cove up`,
# `cove vault unseal`, and the `cove serve run` payload stay consistent.
UNSEAL_HINT = "Run `cove vault unseal` (after unlocking the login keychain)."


def unseal_or_warn(*, context: str) -> bool:
    """Unseal Vault; True on success, False on failure (never raises).

    The non-fatal variant for the login agent: an unseal failure must not abort
    the converge. Prints a clear warning naming the fix and returns False.
    """
    try:
        ensure_unsealed()
    except RuntimeError as exc:
        click.echo(
            f"WARNING: {context} could not be unsealed automatically: {exc}. "
            f"{UNSEAL_HINT}",
            err=True,
        )
        return False
    click.echo("Vault unsealed from the OS keystore.")
    return True


@click.group("vault", help="Manage the local Vault.")
def vault() -> None:
    """Vault lifecycle verbs. See `cove vault unseal`."""


@vault.command("unseal")
def vault_unseal() -> None:
    """Unseal Vault from the OS keystore (Shamir keys).

    Idempotent: a Vault that is already unsealed is left alone. Unlike the
    autostart path, this fails loud — an operator running it by hand wants to
    know the keychain read or the unseal POST failed.

    Examples:

        cove vault unseal
    """
    try:
        ensure_unsealed()
    except RuntimeError as exc:
        raise click.ClickException(
            f"Could not unseal Vault: {exc}\n{UNSEAL_HINT}"
        ) from exc
    click.echo("Vault unsealed from the OS keystore.")
