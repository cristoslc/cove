"""CLI commands for credential lifecycle management."""

import os
import stat
import sys
import tempfile
from pathlib import Path

import click

from cove import op_bulk_write, vault_cache
from cove.stateless import detect_hostname


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
    # Durable store for the Renovate merge automation's Forgejo token. The
    # resolver in scripts/renovate/age_gated_merge.py reads FORGEJO_TOKEN first,
    # then `cove creds vault-get forgejo-token`; this entry is what makes that
    # second path resolve to a real reference. The token belongs to the
    # `renovate-bot` Forgejo account (docs/guides/renovate.md).
    "forgejo_token": "op://Private/Renovate Bot (git.cove)/token",
}

# Credentials only operator automation needs. batch-pull runs on every
# `cove up`, so pulling one of these on a machine that never runs that
# automation would fail the whole converge when its 1Password item is absent.
# They stay resolvable by name for vault-get/vault-put, and out of batch-pull.
BATCH_PULL_EXCLUDED = frozenset({"forgejo_token"})

USERNAME = os.environ.get("USER", "")


def _hostname() -> str:
    """Resolve the stable machine hostname (see detect_hostname).

    Lazily resolved so importing this module (e.g. `cove` CLI startup) does
    not spawn `scutil` for commands that never touch credentials.
    """
    return detect_hostname()


def resolve_ref(ref: str) -> str:
    """Return an op:// reference for a credential name or pass a ref through.

    `cove creds vault-get forgejo-token` is the documented read path for the
    Renovate merge automation, so a bare name is a first-class spelling of the
    reference in OP_REFS. Placeholders are filled only when the template has
    one, which keeps a placeholder-free lookup from spawning `scutil`.
    """
    if ref.startswith("op://"):
        return ref
    key = ref.strip().lower().replace("-", "_")
    template = OP_REFS.get(key)
    if template is None:
        names = ", ".join(sorted(name.replace("_", "-") for name in OP_REFS))
        raise ValueError(
            f"unknown credential name: {ref!r}. Use an op:// reference or one "
            f"of: {names}"
        )
    if "{" in template:
        return template.format(hostname=_hostname(), username=USERNAME)
    return template


def _batch_refs() -> list[str]:
    """The references batch-pull pulls: OP_REFS minus the operator-only ones."""
    return [
        (t.format(hostname=_hostname(), username=USERNAME) if "{" in t else t)
        for key, t in OP_REFS.items()
        if key not in BATCH_PULL_EXCLUDED
    ]


def _excluded_name_for(op_ref: str) -> str:
    """The CLI name of an operator-only ref, or "" when batch-pull covers it.

    Keeps the not-cached error from sending an operator to `batch-pull`, which
    deliberately skips these references.
    """
    for key, template in OP_REFS.items():
        if key in BATCH_PULL_EXCLUDED and "{" not in template and template == op_ref:
            return key.replace("_", "-")
    return ""


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
    help=(
        "Accepted for backward compatibility; vault-put always re-reads "
        "1Password, so this flag no longer changes behavior."
    ),
)
def vault_put(op_ref: str, force_refresh: bool):
    """Cache an op:// reference in Vault from a FRESH 1Password read; never print the resolved value.

    Contract (issue #93): vault-put is sync-from-1Password into the cache.
    It ALWAYS re-reads 1Password and overwrites the Vault and local caches
    with the freshly read value, even when the value is already cached, so
    it never reports success while keeping a stale value after an upstream
    rotation. A 1Password read failure exits non-zero and leaves the caches
    untouched. Cached-if-present short-circuiting belongs to read paths
    (vault-get), not to this sync command. --force-refresh is still
    accepted but is redundant.

    Stdout carries the batch-pull-style mask only — the resolved secret must
    never land in a terminal or agent transcript. Internal callers (tunnel,
    litellm, speedtest up-flows) resolve the value in-process via
    ``cove.vault_cache.vault_put_op_ref`` instead of parsing stdout.

    Examples:

        cove creds vault-put 'op://Private/Forgejo MacBook Admin/password'

        cove creds vault-put forgejo-token

        cove creds vault-put 'op://Private/My Secret/password'
    """
    try:
        op_ref = resolve_ref(op_ref)
    except ValueError as e:
        raise click.ClickException(str(e))
    try:
        value = vault_cache.vault_put_op_ref(op_ref, force_refresh=force_refresh)
    except (ValueError, RuntimeError) as e:
        raise click.ClickException(str(e))
    click.echo(f"  {op_ref}: {'*' * 16}")


@creds.command("vault-get")
@click.argument("op_ref")
def vault_get(op_ref: str):
    """Read a cached op:// reference. Checks local cache first, then Vault.

    Examples:

        cove creds vault-get 'op://Private/Forgejo MacBook Admin/password'

        cove creds vault-get forgejo-token

        cove creds vault-get 'op://Private/Vault MacBook user/password'
    """
    from cove import local_cache as lc

    try:
        op_ref = resolve_ref(op_ref)
    except ValueError as e:
        raise click.ClickException(str(e))
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
    excluded = _excluded_name_for(op_ref)
    if excluded:
        raise click.ClickException(
            f"{op_ref} is not cached. Run `cove creds vault-put {excluded}` "
            "first (it needs a signed-in 1Password CLI and the item)."
        )
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

    refs = _batch_refs()
    if not force_refresh:
        cached = sum(1 for ref in refs if lc.get(ref) is not None)
        if cached == len(refs):
            click.echo("All refs already in local cache. Use --force-refresh to repull.")
            return

    try:
        result = lc.batch_pull(refs)
    except RuntimeError as e:
        raise click.ClickException(str(e))

    for ref, value in result.items():
        click.echo(f"  {ref}: {'*' * 16}")
    click.echo(f"Pulled {len(result)} reference(s) into local cache.")
