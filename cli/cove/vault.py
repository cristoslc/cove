"""`cove vault` — local Vault lifecycle verbs.

`up` is the idempotent converge: ensure the service is running, wait for the
API, then unseal only when sealed. It fails loud on every step it cannot
complete — an operator asking for "one command that leaves Vault usable" wants
the reason, not a warning.

`unseal` wraps `cove.vault_unseal.ensure_unsealed`: read the Shamir unseal keys
from the OS keystore and POST them to Vault. Standalone on purpose — an operator
can unseal without re-running `cove up` (operator decision 2026-10-22; see
docs/musings/cove-serve-autostart.md). Unlike `cove up`'s last-step heal, both
`cove vault` verbs are fail-loud.
"""

from __future__ import annotations

import subprocess
import time

import click

from cove.stateless import ensure_compose_source_ready, resolve_compose_dir
from cove.vault_unseal import ensure_unsealed, vault_health

VAULT_SERVICE = "vault"
VAULT_READY_TIMEOUT_S = 60.0
VAULT_READY_POLL_S = 2.0
VAULT_HEALTH_TIMEOUT_S = 5.0

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


def _compose_up_vault() -> None:
    """`docker compose up -d vault` against the deployed compose source."""
    compose_dir = resolve_compose_dir()
    ensure_compose_source_ready(compose_dir)
    cmd = [
        "docker", "compose",
        "--project-directory", str(compose_dir),
        "up", "-d", VAULT_SERVICE,
    ]
    try:
        subprocess.run(cmd, check=True)
    except FileNotFoundError as exc:
        raise click.ClickException(
            f"docker is not installed or not on PATH: {exc}"
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise click.ClickException(
            f"Could not start the Vault service "
            f"(docker compose up exited {exc.returncode})."
        ) from exc


def _wait_ready(
    timeout_s: float | None = None, poll_s: float | None = None
) -> dict:
    """Poll the Vault API until it answers, or fail after a bounded wait.

    "Ready" means the health endpoint responds at all. A sealed Vault answers
    with HTTP 503, which is ready enough to unseal; the container healthcheck
    (`vault status`) deliberately fails while sealed, so it cannot be used here.
    """
    timeout = VAULT_READY_TIMEOUT_S if timeout_s is None else timeout_s
    interval = VAULT_READY_POLL_S if poll_s is None else poll_s
    deadline = time.monotonic() + timeout
    last_error = "no response"
    while True:
        try:
            return vault_health(timeout=VAULT_HEALTH_TIMEOUT_S)
        except (RuntimeError, OSError) as exc:
            last_error = str(exc)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise click.ClickException(
                f"Vault did not become ready within {timeout:g}s "
                f"(last error: {last_error}). Check `docker compose logs "
                f"{VAULT_SERVICE}` and that ingress is reachable "
                f"(`cove status`)."
            )
        time.sleep(min(interval, remaining))


@click.group("vault", help="Manage the local Vault.")
def vault() -> None:
    """Vault lifecycle verbs. See `cove vault up` and `cove vault unseal`."""


@vault.command("up")
def vault_up() -> None:
    """Start the Vault service and unseal it if sealed (idempotent).

    Ensures the container is up, waits for the API to answer, then unseals a
    sealed-but-initialized Vault from the OS keystore. An already-unsealed
    Vault is left alone. Every step is fail-loud: the command exits non-zero
    when it cannot leave the Vault usable.

    Examples:

        cove vault up
    """
    click.echo("Starting the Vault service...")
    _compose_up_vault()

    health = _wait_ready()
    if not health.get("initialized", False):
        raise click.ClickException(
            "Vault is running but not initialized. Initialize it with "
            "`cove up` (provisioning) or "
            "`ansible-playbook -i inventory.yml bootstrap_vault.yml`."
        )

    if not health.get("sealed", True):
        click.echo("Vault is up and already unsealed.")
        return

    try:
        ensure_unsealed()
    except (RuntimeError, OSError) as exc:
        raise click.ClickException(
            f"Vault is running but could not be unsealed: {exc}\n{UNSEAL_HINT}"
        ) from exc
    click.echo("Vault is up and unsealed.")


@vault.command("status")
def vault_status() -> None:
    """Report whether Vault is initialized, sealed, or unsealed.

    Exits non-zero when Vault is unreachable, uninitialized, or sealed, so the
    state is explicit to scripts as well as to a human reading the output.

    Examples:

        cove vault status
    """
    try:
        health = vault_health(timeout=VAULT_HEALTH_TIMEOUT_S)
    except (RuntimeError, OSError) as exc:
        raise click.ClickException(
            f"Vault is unreachable: {exc}\n"
            "Run `cove vault up` to start and unseal it."
        ) from exc

    if not health.get("initialized", False):
        click.echo("Vault: not initialized")
        raise SystemExit(1)

    if health.get("sealed", True):
        click.echo("Vault: initialized, sealed")
        click.echo("Run `cove vault up` to unseal it.")
        raise SystemExit(1)

    click.echo("Vault: initialized, unsealed")


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
