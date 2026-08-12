"""CLI commands for Speedtest Tracker lifecycle."""

import base64
import os
import secrets
import subprocess

import click

from cove.stateless import resolve_compose_dir


SPEEDTEST_URL = "https://speedtest.cove.local/"
SPEEDTEST_OP_VAULT = "Private"
SPEEDTEST_ITEM_TITLE = "Speedtest Tracker"
APP_KEY_OP_REF_TEMPLATE = (
    f"op://{SPEEDTEST_OP_VAULT}/{SPEEDTEST_ITEM_TITLE}/app_key"
)
SPEEDTEST_ADMIN_USERNAME_OP_REF = (
    f"op://{SPEEDTEST_OP_VAULT}/{SPEEDTEST_ITEM_TITLE}/username"
)
SPEEDTEST_ADMIN_PASSWORD_OP_REF = (
    f"op://{SPEEDTEST_OP_VAULT}/{SPEEDTEST_ITEM_TITLE}/password"
)


def _generate_app_key() -> str:
    """Generate a Speedtest Tracker APP_KEY in the required `base64:` format.

    Speedtest Tracker (Laravel) requires APP_KEY as `base64:<32-byte base64>`.
    A raw string causes HTTP 500 'Unsupported cipher or incorrect key length'.
    """
    return "base64:" + base64.b64encode(secrets.token_bytes(32)).decode()


# Speedtest Tracker's admin login uses an EMAIL address, not a username.
# A cove-specific email (shared across machines) is used for the admin identity.
SPEEDTEST_ADMIN_EMAIL = "admin@cove.local"


# A small portable wordlist for word-based passphrases.
# Kept in-repo (not /usr/share/dict/words) so it works on any platform.
_FRIENDLY_WORDS = (
    "acorn", "amber", "breeze", "canyon", "daisy", "ember", "falcon",
    "garden", "harbor", "iris", "juniper", "kestrel", "lagoon", "meadow",
    "nimbus", "ocean", "pixel", "quartz", "river", "summit", "tundra",
    "willow", "zephyr",
)


def _passphrase() -> str:
    """Return a word-based passphrase (hyphen-separated words), not random
    alphanumeric. 4 words from a 23-word list ≈ 4 * log2(23) ≈ 18 bits of
    entropy — adequate for a local single-operator service."""
    return "-".join(secrets.choice(_FRIENDLY_WORDS) for _ in range(4))


def _compose_dir():
    return resolve_compose_dir()


def _compose_env_path():
    return _compose_dir() / ".env"


def _app_key_op_ref() -> str:
    return APP_KEY_OP_REF_TEMPLATE


def _seed_example_path():
    return _compose_dir() / "seeds" / "speedtest-creds.yaml.example"


def _render_seed() -> str:
    """Render the speedtest seed template into a shared, URL-keyed 1Password
    item (title 'Speedtest Tracker' keyed to `https://speedtest.cove.local/`,
    NOT per-hostname), so the same credentials work on all the operator's
    machines.

    The `{{generate:N}}` placeholders are replaced with a base64-prefixed
    APP_KEY (Speedtest Tracker/Laravel requires that format; a raw string
    causes HTTP 500), the admin email, and a word-based passphrase."""
    template = _seed_example_path().read_text()
    rendered = template.replace("{{generate:64}}", _generate_app_key())
    rendered = rendered.replace("{{generate:16}}", SPEEDTEST_ADMIN_EMAIL)
    rendered = rendered.replace("{{generate:32}}", _passphrase())
    return rendered


def _seed_path() -> str:
    """Write the rendered seed to a temp file for 1p-bulk-write, returning the
    path. The caller MUST unlink the returned path after use (see
    `_ensure_app_key`)."""
    import tempfile
    fd, path_str = tempfile.mkstemp(
        prefix="cove-speedtest-seed-", suffix=".yaml"
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
            f"Failed to cache Speedtest APP_KEY in Vault: {result.stderr.strip()}"
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


def _ensure_app_key() -> str:
    """Return a usable SPEEDTEST_APP_KEY from the shared Speedtest Tracker
    1Password item keyed to `https://speedtest.cove.local/` (NOT per-hostname).

    On every run we CHECK 1Password for an existing shared item first (via
    `cove creds vault-get` on the shared op_ref) and REUSE it if present — so
    the same credentials work on all the operator's machines. Only if no such
    shared item exists do we generate admin email/password + APP_KEY, write
    them to 1Password (seed + `1p-bulk-write --execute`), cache in Vault
    (`vault-put`), and inject into the compose .env (mirrors the forgejo/minio
    credential pattern).

    IaC: the admin email/password are also injected into the compose .env
    (SPEEDTEST_ADMIN_EMAIL / SPEEDTEST_ADMIN_PASSWORD) so a fresh deploy seeds
    the correct admin user — not the default admin@example.com/password."""
    # 1. Operator explicitly set it — honor directly.
    explicit = os.environ.get("SPEEDTEST_APP_KEY")
    if explicit:
        _upsert_env("SPEEDTEST_APP_KEY", explicit)
        return explicit

    # 2. Already present in the compose .env — reuse (no regen).
    env_path = _compose_env_path()
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("SPEEDTEST_APP_KEY="):
                value = line.split("=", 1)[1].strip()
                if value:
                    return value

    # 3. Shared item already exists in 1Password (cached in Vault) — reuse it.
    #    Checked FIRST so credentials are shared across all the operator's
    #    machines (no per-machine regeneration).
    op_ref = _app_key_op_ref()
    cached = _vault_get(op_ref)
    if cached:
        _upsert_env("SPEEDTEST_APP_KEY", cached)
        _inject_admin_env()
        return cached

    # 4. No shared item exists — generate admin creds + APP_KEY, write the
    #    shared item to 1Password, cache in Vault, inject into .env.
    seed_path = _seed_path()
    try:
        write = _run_cove_creds("1p-bulk-write", seed_path, "--execute")
        if write.returncode != 0:
            raise click.ClickException(
                "Failed to write Speedtest credentials to 1Password: "
                f"{write.stderr.strip()}"
            )
        value = _vault_put(op_ref)
    finally:
        os.unlink(seed_path)
    _upsert_env("SPEEDTEST_APP_KEY", value)
    _inject_admin_env()
    return value


def _inject_admin_env() -> None:
    """Inject the shared admin email/password into the compose .env so a fresh
    deploy seeds the correct admin user (IaC)."""
    email = _vault_get(SPEEDTEST_ADMIN_USERNAME_OP_REF)
    password = _vault_get(SPEEDTEST_ADMIN_PASSWORD_OP_REF)
    if email:
        _upsert_env("SPEEDTEST_ADMIN_EMAIL", email)
    if password:
        _upsert_env("SPEEDTEST_ADMIN_PASSWORD", password)


def _compose_cmd(*args: str) -> list[str]:
    compose_dir = resolve_compose_dir()
    return [
        "docker", "compose",
        "--project-directory", str(compose_dir),
        *args,
    ]


@click.group()
def speedtest():
    """Manage the Speedtest Tracker (optional WAN-link monitor).

    Speedtest Tracker monitors the machine's internet connection —
    uptime, latency, and bandwidth. It runs on https://speedtest.cove/
    and is reached only through the nginx ingress.
    """


@speedtest.command()
def up():
    """Start the Speedtest Tracker service.

    Ensures a SPEEDTEST_APP_KEY is available, auto-generating one and storing
    it in 1Password + Vault + the compose .env on first run.
    """
    _ensure_app_key()
    click.echo("Starting Speedtest Tracker...")
    subprocess.run(_compose_cmd("--profile", "speedtest", "up", "-d"), check=True)
    click.echo("Speedtest Tracker is running at https://speedtest.cove/")


@speedtest.command()
def down():
    """Stop the Speedtest Tracker service (data preserved)."""
    click.echo("Stopping Speedtest Tracker...")
    subprocess.run(_compose_cmd("stop", "speedtest-tracker"), check=True)
    click.echo("Speedtest Tracker stopped.")


@speedtest.command()
def status():
    """Check Speedtest Tracker health."""
    result = subprocess.run(
        _compose_cmd("ps", "--filter", "name=cove-speedtest-tracker",
                     "--format", "table {{.Name}}\t{{.Status}}\t{{.Ports}}"),
        capture_output=True, text=True,
    )
    click.echo(result.stdout)
    if result.returncode != 0:
        raise SystemExit(result.returncode)

    click.echo("Checking speedtest.cove through nginx...")
    for host in ("speedtest.cove.local", "speedtest.cove"):
        health = subprocess.run(
            ["curl", "-sf", "-H", f"Host: {host}", "https://127.0.0.1:8443/"],
            capture_output=True, text=True, timeout=10,
        )
        if health.returncode == 0:
            click.echo("  Health: OK")
            return
    click.echo("  Health: UNREACHABLE")
    raise SystemExit(1)


@speedtest.command()
@click.option("-n", "--lines", default=50, help="Number of lines to show.")
@click.option("-f", "--follow", is_flag=True, help="Follow log output.")
def logs(lines, follow):
    """Tail Speedtest Tracker logs."""
    cmd = _compose_cmd("logs", "--tail", str(lines))
    if follow:
        cmd.append("--follow")
    subprocess.run(cmd, check=True)
