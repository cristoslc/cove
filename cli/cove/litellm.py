"""CLI commands for LiteLLM proxy lifecycle."""

import os
import subprocess
import tempfile

import click

from cove.stateless import resolve_compose_dir


LITELLM_URL = "https://litellm.cove.local/"
LITELLM_OP_VAULT = "Private"
LITELLM_ITEM_TITLE = "LiteLLM Proxy"
# The shared Cove admin identity (ADR-017) lives in a cove.local-keyed item,
# NOT a per-service item. The LiteLLM master key stays in the LiteLLM Proxy
# item; the UI username/password come from the shared Cove Admin item.
COVE_ADMIN_ITEM_TITLE = "Cove Admin"
MASTER_KEY_OP_REF = f"op://{LITELLM_OP_VAULT}/{LITELLM_ITEM_TITLE}/master_key"
UI_USERNAME_OP_REF = f"op://{LITELLM_OP_VAULT}/{COVE_ADMIN_ITEM_TITLE}/username"
UI_PASSWORD_OP_REF = f"op://{LITELLM_OP_VAULT}/{COVE_ADMIN_ITEM_TITLE}/password"


def _compose_cmd(*args: str) -> list[str]:
    compose_dir = resolve_compose_dir()
    return [
        "docker", "compose",
        "--project-directory", str(compose_dir),
        *args,
    ]


def _compose_env_path():
    return resolve_compose_dir() / ".env"


def _seed_example_path():
    return resolve_compose_dir() / "seeds" / "litellm-creds.yaml.example"


def _render_seed() -> str:
    """Render the litellm seed template into a shared, URL-keyed 1Password
    item (title 'LiteLLM Proxy' keyed to `https://litellm.cove.local/`,
    NOT per-hostname), so the same master key works on all the operator's
    machines.

    The item holds ONLY the master key. The UI username/password come from the
    shared 'Cove Admin' item (keyed to https://cove.local/, ADR-017), the
    unified Cove admin identity used across all Cove services.

    The `{{generate:32}}` placeholder is replaced with a random master key
    (LiteLLM master keys must start with `sk-` to authorize /health, so the
    generated value is prefixed)."""
    template = _seed_example_path().read_text()
    return template.replace("{{generate:32}}", "sk-" + _generate_master_key())


def _generate_master_key() -> str:
    import secrets
    import string

    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(32))


def _seed_path() -> str:
    """Write the rendered seed to a temp file for 1p-bulk-write, returning the
    path. The caller MUST unlink the returned path after use."""
    fd, path_str = tempfile.mkstemp(
        prefix="cove-litellm-seed-", suffix=".yaml"
    )
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
    """Cache op_ref in Vault and return the resolved value."""
    result = _run_cove_creds("vault-put", op_ref)
    if result.returncode != 0:
        raise click.ClickException(
            f"Failed to cache LiteLLM master key in Vault: {result.stderr.strip()}"
        )
    return result.stdout.strip()


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


def _ensure_master_key() -> str:
    """Return a usable LITELLM_MASTER_KEY from the shared LiteLLM Proxy
    1Password item keyed to `https://litellm.cove.local/` (NOT per-hostname).

    On every run we CHECK 1Password for an existing shared item first (via
    `cove creds vault-get` on the shared op_ref) and REUSE it if present — so
    the same credentials work on all the operator's machines. Only if no such
    shared item exists do we generate a master key, write it to 1Password
    (seed + `1p-bulk-write --execute`), cache in Vault (`vault-put`), and
    inject into the compose .env (mirrors the speedtest/forgejo/minio
    credential pattern).

    IaC: the UI username/password are also injected into the compose .env
    (LITELLM_UI_USERNAME / LITELLM_UI_PASSWORD) so a fresh deploy seeds the
    correct admin identity — never a weak default master key."""
    # 1. Operator explicitly set it — honor directly.
    explicit = os.environ.get("LITELLM_MASTER_KEY")
    if explicit:
        _upsert_env("LITELLM_MASTER_KEY", explicit)
        _inject_admin_env()
        return explicit

    # 2. Already present in the compose .env — reuse (no regen).
    env_path = _compose_env_path()
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("LITELLM_MASTER_KEY="):
                value = line.split("=", 1)[1].strip()
                if value:
                    _inject_admin_env()
                    return value

    # 3. Shared item already exists in 1Password (cached in Vault) — reuse it.
    #    Checked FIRST so credentials are shared across all the operator's
    #    machines (no per-machine regeneration).
    cached = _vault_get(MASTER_KEY_OP_REF)
    if cached:
        _upsert_env("LITELLM_MASTER_KEY", cached)
        _inject_admin_env()
        return cached

    # 4. No shared item exists — generate a master key, write the shared item
    #    to 1Password, cache in Vault, inject into .env.
    seed_path = _seed_path()
    try:
        write = _run_cove_creds("1p-bulk-write", seed_path, "--execute")
        if write.returncode != 0:
            raise click.ClickException(
                "Failed to write LiteLLM credentials to 1Password: "
                f"{write.stderr.strip()}"
            )
        value = _vault_put(MASTER_KEY_OP_REF)
    finally:
        os.unlink(seed_path)
    _upsert_env("LITELLM_MASTER_KEY", value)
    _inject_admin_env()
    return value


def _inject_admin_env() -> None:
    """Inject the shared admin username/password into the compose .env so a
    fresh deploy seeds the correct admin identity (IaC).

    Fail loud: if the shared 'Cove Admin' item (ADR-017) is absent, raise —
    never silently fall back to a default admin."""
    username = _vault_get(UI_USERNAME_OP_REF)
    password = _vault_get(UI_PASSWORD_OP_REF)
    if not username or not password:
        raise click.ClickException(
            "LiteLLM UI admin identity is missing. The shared 'Cove Admin' "
            "1Password item (keyed to https://cove.local/, ADR-017) must exist "
            "with username and password fields. Run `cove creds batch-pull` or "
            "provision the Cove Admin item first."
        )
    _upsert_env("LITELLM_UI_USERNAME", username)
    _upsert_env("LITELLM_UI_PASSWORD", password)


@click.group()
def litellm():
    """Manage the LiteLLM proxy (optional harbor service).

    LiteLLM is a hardened LLM proxy with Headroom compression.
    It runs on https://litellm.cove/ and proxies to upstream providers.
    """


@litellm.command()
def up():
    """Start the LiteLLM proxy and Headroom sidecar."""
    _ensure_master_key()
    click.echo("Starting LiteLLM proxy...")
    subprocess.run(_compose_cmd("--profile", "litellm", "up", "-d", "--build"), check=True)
    click.echo("LiteLLM proxy is running at https://litellm.cove/")


@litellm.command()
def down():
    """Stop the LiteLLM proxy and Headroom sidecar."""
    click.echo("Stopping LiteLLM proxy...")
    subprocess.run(_compose_cmd("stop", "litellm", "headroom"), check=True)
    click.echo("LiteLLM proxy stopped.")


@litellm.command()
def status():
    """Check LiteLLM proxy health."""
    result = subprocess.run(
        _compose_cmd("ps", "--format", "table {{.Name}}\t{{.Status}}\t{{.Ports}}"),
        capture_output=True, text=True,
    )
    click.echo(result.stdout)
    if result.returncode != 0:
        raise SystemExit(result.returncode)

    click.echo("Checking /health/readiness through nginx...")
    for host in ("litellm.cove.local", "litellm.cove"):
        health = subprocess.run(
            ["curl", "-sf", "-H", f"Host: {host}", "https://127.0.0.1:8443/health/readiness"],
            capture_output=True, text=True, timeout=10,
        )
        if health.returncode == 0:
            click.echo("  Health: OK")
            return
    click.echo("  Health: UNREACHABLE")
    raise SystemExit(1)


@litellm.command()
@click.option("-n", "--lines", default=50, help="Number of lines to show.")
@click.option("-f", "--follow", is_flag=True, help="Follow log output.")
def logs(lines, follow):
    """Tail LiteLLM proxy logs."""
    cmd = _compose_cmd("logs", "--tail", str(lines))
    if follow:
        cmd.append("--follow")
    subprocess.run(cmd, check=True)
