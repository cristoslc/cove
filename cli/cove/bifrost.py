"""CLI commands for the Bifrost gateway lifecycle.

LiteLLM replacement candidate, ADDITIVE phase (docs/musings/litellm-exit.md):
`cove bifrost` manages the bifrost compose profile alongside the live
litellm services — nothing is removed and no client is re-pointed by this
module (the client-facing re-point is a later, workstation-lane-gated phase).
"""

import json
import os
import secrets
import sqlite3
import string
import subprocess
import tempfile
from pathlib import Path

import click

from cove.constants import NGINX_HTTPS_PORT
from cove.stateless import resolve_compose_dir, ensure_compose_source_ready
# Shared 4-word passphrase helper (speedtest's admin password generator);
# importing keeps a single source of truth for the wordlist.
from cove.speedtest import _passphrase as _friendly_passphrase


BIFROST_URL = "https://bifrost.cove.local/"
BIFROST_OP_VAULT = "Private"
BIFROST_ITEM_TITLE = "Bifrost Gateway"
# The shared Cove admin identity (ADR-017) lives in a cove.local-keyed item,
# NOT a per-service item. Encryption key / dashboard password / virtual key
# live in the Bifrost Gateway item; the admin username comes from the shared
# Cove Admin item.
COVE_ADMIN_ITEM_TITLE = "Cove Admin"
ENCRYPTION_KEY_OP_REF = f"op://{BIFROST_OP_VAULT}/{BIFROST_ITEM_TITLE}/encryption_key"
ADMIN_PASSWORD_OP_REF = f"op://{BIFROST_OP_VAULT}/{BIFROST_ITEM_TITLE}/admin_password"
VIRTUAL_KEY_OP_REF = f"op://{BIFROST_OP_VAULT}/{BIFROST_ITEM_TITLE}/virtual_key"
ADMIN_USERNAME_OP_REF = f"op://{BIFROST_OP_VAULT}/{COVE_ADMIN_ITEM_TITLE}/username"


def _compose_cmd(*args: str) -> list[str]:
    compose_dir = resolve_compose_dir()
    return [
        "docker", "compose",
        "--project-directory", str(compose_dir),
        *args,
    ]


def _compose_env_path():
    return resolve_compose_dir() / ".env"


def _cove_data_root() -> Path:
    explicit = os.environ.get("COVE_DATA_ROOT")
    if explicit:
        return Path(explicit).expanduser()
    env_path = _compose_env_path()
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("COVE_DATA_ROOT="):
                value = line.split("=", 1)[1].strip().strip("\"'")
                if value:
                    return Path(value).expanduser()
    return Path.home() / "Documents" / "cove-data"


def _generate_encryption_key() -> str:
    # 32 random bytes, hex-encoded → 64 chars; Bifrost derives its
    # at-rest/config-store encryption key from this value.
    return secrets.token_hex(32)


def _generate_virtual_key() -> str:
    alphabet = string.ascii_letters + string.digits
    body = "".join(secrets.choice(alphabet) for _ in range(32))
    return f"bf-{body}"


def _seed_example_path():
    return resolve_compose_dir() / "seeds" / "bifrost-creds.yaml.example"


def _render_seed() -> str:
    """Render the bifrost seed template into a shared, URL-keyed 1Password
    item (title 'Bifrost Gateway' keyed to `https://bifrost.cove.local/`),
    so the same credentials work on all the operator's machines.

    The item holds the config-store encryption key, the dashboard admin
    password, and the client-facing virtual key. The admin USERNAME comes
    from the shared 'Cove Admin' item (https://cove.local/, ADR-017).

    Each field carries its own placeholder so the three values are always
    distinct:"""
    template = _seed_example_path().read_text()
    rendered = template
    rendered = rendered.replace("{{generate:encryption_key}}", _generate_encryption_key())
    rendered = rendered.replace("{{generate:admin_password}}", _friendly_passphrase())
    rendered = rendered.replace("{{generate:virtual_key}}", _generate_virtual_key())
    return rendered


def _seed_path() -> str:
    """Write the rendered seed to a temp file for 1p-bulk-write, returning the
    path. The caller MUST unlink the returned path after use."""
    fd, path_str = tempfile.mkstemp(prefix="cove-bifrost-seed-", suffix=".yaml")
    with os.fdopen(fd, "w") as f:
        f.write(_render_seed())
    return path_str


def _run_cove_creds(*args: str) -> subprocess.CompletedProcess:
    """Run `cove creds ...`, capturing stdout so we can resolve the secret."""
    return subprocess.run(
        ["cove", "creds", *args],
        capture_output=True, text=True, stdin=subprocess.DEVNULL,
        check=False,
    )


def _vault_get(op_ref: str):
    """Return the cached Vault value for op_ref, or None if not cached."""
    result = _run_cove_creds("vault-get", op_ref)
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _vault_put(op_ref: str) -> str:
    """Cache op_ref in Vault and return the resolved value (in-process).

    `cove creds vault-put` stdout is masked and never carries the secret; the
    value comes straight from vault_cache so it can never enter a transcript.
    """
    from cove import vault_cache
    try:
        return vault_cache.vault_put_op_ref(op_ref)
    except (ValueError, RuntimeError) as e:
        raise click.ClickException(
            f"Failed to cache Bifrost credential in Vault: {e}"
        )


def _upsert_env(key: str, value: str) -> None:
    """Set KEY=VALUE in the compose .env idempotently (no duplicate lines)."""
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


def _ensure_secret(
    env_key: str,
    op_ref: str,
    generate,
) -> str:
    """One secret, in the litellm/speedtest order: explicit env → compose
    .env reuse → shared 1Password item reuse → generate + 1P item + Vault."""
    # 1. Operator explicitly set it — honor directly.
    explicit = os.environ.get(env_key)
    if explicit:
        _upsert_env(env_key, explicit)
        return explicit

    # 2. Already present in the compose .env — reuse (no regen).
    env_path = _compose_env_path()
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith(f"{env_key}="):
                value = line.split("=", 1)[1].strip()
                if value:
                    return value

    # 3. Shared item already exists in 1Password (cached in Vault) — reuse.
    cached = _vault_get(op_ref)
    if cached:
        _upsert_env(env_key, cached)
        return cached

    # 4. Generate, write the shared item to 1Password (seed + bulk write),
    #    cache in Vault, inject into .env.
    seed_path = _seed_path()
    try:
        write = _run_cove_creds("1p-bulk-write", seed_path, "--execute")
        if write.returncode != 0:
            raise click.ClickException(
                f"Failed to write Bifrost credentials to 1Password: "
                f"{write.stderr.strip()}"
            )
        value = _vault_put(op_ref)
    finally:
        os.unlink(seed_path)
    _upsert_env(env_key, value)
    return value


def _ensure_secrets() -> None:
    """Provision the three Bifrost credentials into the compose .env, reusing
    the shared 1Password items across machines. Also injects the shared Cove
    Admin username (dashboard identity). Never prints a secret value."""
    _ensure_secret(
        "BIFROST_ENCRYPTION_KEY",
        ENCRYPTION_KEY_OP_REF,
        _generate_encryption_key,
    )
    _ensure_secret(
        "BIFROST_ADMIN_PASSWORD",
        ADMIN_PASSWORD_OP_REF,
        _friendly_passphrase,
    )
    _ensure_secret(
        "BIFROST_VIRTUAL_KEY",
        VIRTUAL_KEY_OP_REF,
        _generate_virtual_key,
    )

    # Shared Cove Admin username (ADR-017) — the dashboard identity. Fail
    # loud when the shared item is absent; never fall back to a default.
    username = _vault_get(ADMIN_USERNAME_OP_REF)
    if not username:
        raise click.ClickException(
            "Bifrost dashboard admin username is missing. The shared "
            "'Cove Admin' 1Password item (keyed to https://cove.local/, "
            "ADR-017) must exist with a username field. Run "
            "`cove creds batch-pull` or provision the Cove Admin item first."
        )
    _upsert_env("BIFROST_ADMIN_USERNAME", username)


def _ensure_runtime_files() -> None:
    """Seed the data-root runtime files for the bifrost profile.

    - bifrost/ dir: operator-private (0700) — it holds provider key env files.
    - local.env: 0600, left EMPTY (keys come from litellm's local.env pattern
      or operator edits); never overwritten.
    - config.json / dnsmasq.conf: seeded from the compose source, first boot
      only (operator edits preserved).
    - config.db: the SQLite config store file must pre-exist before first
      boot (a file-only config.json boot cannot carry governance); created
      as a valid empty SQLite database, 0600, never recreated if present.
    """
    compose_dir = resolve_compose_dir()
    data_root = _cove_data_root()
    config_dir = data_root / "bifrost"
    config_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    config_dir.chmod(0o700)

    env_file = config_dir / "local.env"
    if not env_file.exists():
        env_file.write_text("")
    env_file.chmod(0o600)

    for name in ("config.json", "dnsmasq.conf"):
        src = compose_dir / "bifrost" / name
        dest = config_dir / name
        if not src.exists():
            raise click.ClickException(
                f"Bifrost source config {src} is missing — compose source "
                "is not synced; run with provisioning or reinstall cove."
            )
        if not dest.exists():
            dest.write_text(src.read_text())
            dest.chmod(0o644)

    store = config_dir / "config.db"
    if not store.exists():
        # Touch-by-connect: a valid, empty SQLite database file. Bifrost
        # mounts this file writable and carries governance itself.
        try:
            conn = sqlite3.connect(store)
            conn.close()
        except sqlite3.Error as e:
            raise click.ClickException(
                f"Failed to pre-seed the Bifrost SQLite config store at "
                f"{store}: {e}"
            )
    store.chmod(0o600)


def _env_flag_set(env_key: str) -> bool:
    """TRUE when a compose .env line exists with a non-empty value. Values
    are never echoed."""
    env_path = _compose_env_path()
    if not env_path.exists():
        return False
    for line in env_path.read_text().splitlines():
        if line.startswith(f"{env_key}="):
            return bool(line.split("=", 1)[1].strip())
    return False


def _local_env_flag_set(name: str) -> bool:
    """TRUE when the bifrost local.env carries NAME=<non-empty>."""
    env_file = _cove_data_root() / "bifrost" / "local.env"
    if not env_file.exists():
        return False
    for line in env_file.read_text().splitlines():
        if line.startswith(f"{name}="):
            return bool(line.split("=", 1)[1].strip())
    return False


@click.group()
def bifrost():
    """Manage the Bifrost gateway (optional harbor service).

    LiteLLM replacement candidate, additive phase: runs on the bifrost
    compose profile alongside the live litellm services. Client-facing at
    https://bifrost.cove.local/ (the client re-point is a later, gated
    phase; litellm remains the agent traffic path today).
    """


@bifrost.command()
def up():
    """Start the Bifrost gateway and its egress sinkhole."""
    ensure_compose_source_ready(resolve_compose_dir())
    _ensure_secrets()
    _ensure_runtime_files()
    click.echo("Starting Bifrost gateway (profile: bifrost)...")
    subprocess.run(_compose_cmd("--profile", "bifrost", "up", "-d", "--build"), check=True)
    click.echo(f"Bifrost gateway is running. Gateway: {BIFROST_URL}")


@bifrost.command()
def down():
    """Stop the Bifrost gateway and its egress sinkhole."""
    ensure_compose_source_ready(resolve_compose_dir())
    click.echo("Stopping Bifrost gateway...")
    subprocess.run(_compose_cmd("stop", "bifrost", "bifrost-dns"), check=True)
    click.echo("Bifrost gateway stopped.")


@bifrost.command()
def status():
    """Check Bifrost gateway health and credential wiring."""
    result = subprocess.run(
        _compose_cmd("ps", "--format", "table {{.Name}}\t{{.Status}}\t{{.Ports}}"),
        capture_output=True, text=True,
    )
    click.echo(result.stdout)
    if result.returncode != 0:
        if result.stderr:
            click.echo(result.stderr)
        raise SystemExit(result.returncode)

    click.echo("Credential wiring (names only, values never printed):")
    click.echo(
        "  Synthetic key (local.env SYNTHETIC_API_KEY): "
        + ("SET" if _local_env_flag_set("SYNTHETIC_API_KEY") else "missing")
    )
    click.echo(
        "  ollama-cloud key (pass-through OLLAMA_API_KEY): "
        + ("SET" if _env_flag_set("OLLAMA_API_KEY") else "missing")
    )
    for key in ("BIFROST_ENCRYPTION_KEY", "BIFROST_ADMIN_USERNAME",
                "BIFROST_ADMIN_PASSWORD", "BIFROST_VIRTUAL_KEY"):
        click.echo(
            f"  {key}: " + ("SET" if _env_flag_set(key) else "missing")
        )

    click.echo("Checking /health through nginx...")
    for host in ("bifrost.cove.local", "bifrost.cove"):
        try:
            health = subprocess.run(
                ["curl", "-sf", "-H", f"Host: {host}",
                 f"https://127.0.0.1:{NGINX_HTTPS_PORT}/health"],
                capture_output=True, text=True, timeout=10,
            )
        except subprocess.TimeoutExpired:
            continue
        if health.returncode == 0:
            click.echo("  Health: OK")
            return
    click.echo("  Health: UNREACHABLE")
    raise SystemExit(1)


@bifrost.command()
@click.option("-n", "--lines", default=50, help="Number of lines to show.")
@click.option("-f", "--follow", is_flag=True, help="Follow log output.")
def logs(lines, follow):
    """Tail Bifrost gateway logs."""
    cmd = _compose_cmd("logs", "--tail", str(lines))
    if follow:
        cmd.append("--follow")
    subprocess.run(cmd, check=True)