"""CLI commands for Speedtest Tracker lifecycle."""

import os
import subprocess

import click

from cove.stateless import resolve_compose_dir


APP_KEY_OP_REF_TEMPLATE = "op://Private/Speedtest {hostname} APP_KEY/password"


def _compose_dir():
    return resolve_compose_dir()


def _compose_env_path():
    return _compose_dir() / ".env"


def _hostname() -> str:
    import platform
    return platform.node().split(".")[0]


def _app_key_op_ref() -> str:
    return APP_KEY_OP_REF_TEMPLATE.format(hostname=_hostname())


def _seed_example_path():
    return _compose_dir() / "seeds" / "speedtest-creds.yaml.example"


def _render_seed() -> str:
    """Render the speedtest seed template with the runtime hostname so the
    1Password item title matches the op_ref (mirrors Ansible seed rendering)."""
    template = _seed_example_path().read_text()
    return template.replace("{{ hostname }}", _hostname())


def _seed_path() -> str:
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


def _ensure_app_key() -> str:
    """Return a usable SPEEDTEST_APP_KEY, auto-generating + storing it in
    1Password + Vault + the compose .env on first run (mirrors the forgejo/minio
    credential pattern). Subsequent runs reuse the cached value (idempotent)."""
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

    # 3. Already cached in Vault — reuse (no regen).
    op_ref = _app_key_op_ref()
    cached = _vault_get(op_ref)
    if cached:
        _upsert_env("SPEEDTEST_APP_KEY", cached)
        return cached

    # 4. Auto-generate: seed 1Password, cache in Vault, inject into .env.
    _run_cove_creds("1p-bulk-write", _seed_path(), "--execute")
    value = _vault_put(op_ref)
    _upsert_env("SPEEDTEST_APP_KEY", value)
    return value


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
    subprocess.run(_compose_cmd("up", "-d", "--profile", "speedtest"), check=True)
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
