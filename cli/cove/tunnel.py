"""CLI commands for the zrok2 public-tunnel sidecar (optional profile)."""

import re
import subprocess

import click

from cove.stateless import resolve_compose_dir


ZROK2_IMAGE = "openziti/zrok2:2.0.4"
ZROK2_DOMAIN = "shares.zrok.io"
TUNNEL_OP_VAULT = "Private"
TUNNEL_ITEM_TITLE = "Zrok Account"
ACCOUNT_TOKEN_OP_REF = f"op://{TUNNEL_OP_VAULT}/{TUNNEL_ITEM_TITLE}/account_token"
SHARE_TOKEN_OP_REF = f"op://{TUNNEL_OP_VAULT}/{TUNNEL_ITEM_TITLE}/share_token"
DEFAULT_TARGET = "https://nginx"
NAME_PATTERN = re.compile(r"^[a-z0-9]{4,32}$")
CONTAINER_NAME = "cove-tunnel"


def validate_share_name(name: str) -> str:
    """Return the normalized share name, or raise a loud error."""
    normalized = name.strip().lower()
    if not NAME_PATTERN.match(normalized):
        raise click.ClickException(
            f"Invalid tunnel name {name!r}: must be lowercase alphanumeric, "
            "4-32 characters (zrok2 reserved-name constraint)."
        )
    return normalized


def _compose_cmd(*args: str) -> list[str]:
    compose_dir = resolve_compose_dir()
    return [
        "docker", "compose",
        "--project-directory", str(compose_dir),
        *args,
    ]


def _compose_env_path():
    return resolve_compose_dir() / ".env"


def _upsert_env(key: str, value: str) -> None:
    """Set KEY=VALUE in the compose .env idempotently (no duplicate lines)."""
    env_path = _compose_env_path()
    lines = []
    if env_path.exists():
        for existing in env_path.read_text().splitlines():
            if existing.startswith(f"{key}="):
                continue
            lines.append(existing)
    lines.append(f"{key}={value}")
    env_path.write_text("\n".join(lines) + "\n")
    env_path.chmod(0o600)


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
            f"Failed to cache zrok2 credential in Vault: {result.stderr.strip()}"
        )
    return result.stdout.strip()


def _ensure_account_token() -> str:
    """Return a usable ZROK_ACCOUNT_TOKEN, failing loud if absent.

    Fail-loud: zrok2 free-tier shares are account-scoped; an anonymous
    fallback would silently create shares under the wrong identity or none
    at all. The token comes from the shared 'Zrok Account' 1Password item
    (ADR-017 conventions), the compose .env, or ZROK_ACCOUNT_TOKEN env —
    never generated, never defaulted."""
    explicit = _env_token("ZROK_ACCOUNT_TOKEN")
    if explicit:
        return explicit

    env_path = _compose_env_path()
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("ZROK_ACCOUNT_TOKEN="):
                value = line.split("=", 1)[1].strip()
                if value:
                    return value

    cached = _vault_get(ACCOUNT_TOKEN_OP_REF)
    if cached:
        _upsert_env("ZROK_ACCOUNT_TOKEN", cached)
        return cached

    raise click.ClickException(
        "zrok2 account token is missing. Sign up at https://myzrok.io/ (no "
        "card required), copy the account token, and store it with: "
        "`cove creds set 'op://Private/Zrok Account/account_token'`. See "
        "docs/services/tunnel.md for the onboarding journey."
    )


def _env_token(key: str):
    import os

    value = os.environ.get(key)
    return value.strip() if value else None


def _zrok2_exec(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run a zrok2 command inside the tunnel sidecar."""
    return subprocess.run(
        _compose_cmd("--profile", "tunnel", "exec", "tunnel", "zrok2", *args),
        check=check,
    )


def _zrok2_exec_capture(
    *args: str, check: bool = True
) -> subprocess.CompletedProcess:
    """Run a zrok2 command inside the sidecar, capturing output."""
    return subprocess.run(
        _compose_cmd("--profile", "tunnel", "exec", "tunnel", "zrok2", *args),
        capture_output=True, text=True, check=check,
    )


def _ensure_sidecar() -> None:
    """Start the tunnel sidecar (outbound-only, no published ports)."""
    subprocess.run(
        _compose_cmd("--profile", "tunnel", "up", "-d"), check=True
    )


def _ensure_enabled() -> None:
    """Run `zrok2 enable` idempotently; state persists in the sidecar volume."""
    env = _zrok2_exec_capture("status", check=False)
    if env.returncode == 0 and "environment enabled" in (env.stdout + env.stderr).lower():
        return
    token = _ensure_account_token()
    result = _zrok2_exec_capture("enable", token, check=False)
    if result.returncode != 0:
        raise click.ClickException(
            "zrok2 enable failed: "
            f"{(result.stderr or result.stdout).strip()}"
        )


def _share_public(target: str, name: str | None) -> str:
    """Start a public share; return the public URL."""
    args = ["share", "public", target, "--headless"]
    if name:
        args += ["-n", f"public:{name}"]
    result = _zrok2_exec_capture(*args, check=False)
    if result.returncode != 0:
        raise click.ClickException(
            "zrok2 share public failed: "
            f"{(result.stderr or result.stdout).strip()}"
        )
    url = _extract_url(result.stdout + result.stderr)
    if not url:
        raise click.ClickException(
            f"Could not parse a public URL from zrok2 output: {result.stdout.strip()}"
        )
    return url


def _extract_url(output: str):
    match = re.search(rf"https://[a-z0-9.-]+{re.escape(ZROK2_DOMAIN)}\S*", output)
    return match.group(0).rstrip(".,;:") if match else None


def _share_private(target: str, share_token: str) -> str:
    """Start a private share with a vanity token; return the token."""
    result = _zrok2_exec_capture(
        "share", "private", target, "--share-token", share_token,
        "--headless", check=False,
    )
    if result.returncode != 0:
        raise click.ClickException(
            "zrok2 share private failed: "
            f"{(result.stderr or result.stdout).strip()}"
        )
    return share_token


def _list_shares() -> list[str]:
    result = _zrok2_exec_capture("list", "shares", check=False)
    return result.stdout.splitlines() if result.returncode == 0 else []


@click.group()
def tunnel():
    """Manage the public tunnel (optional zrok2 relay sidecar).

    Publishes a `.cove` service to the public web via a zrok.io managed
    relay. The sidecar is outbound-only; shares exist only while active.
    """


@tunnel.command()
@click.argument("target", required=False, default=None)
@click.option("--public", "name", default=None, help="Reserve a stable name.")
@click.option("--private", "private_mode", is_flag=True,
              help="Private share: prints a share token, no public URL.")
def up(target, name, private_mode):
    """Start a share for TARGET (default: ingress, Host preserved)."""
    if name:
        name = validate_share_name(name)
    _ensure_sidecar()
    _ensure_enabled()
    resolved_target = target or DEFAULT_TARGET
    if private_mode:
        token = name or _generate_share_token()
        printed = _share_private(resolved_target, token)
        click.echo(f"Private share active. Access with: zrok2 access private {printed}")
        return
    url = _share_public(resolved_target, name)
    click.echo(f"Tunnel active: {url}")


def _generate_share_token() -> str:
    import secrets
    import string

    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(12))


@tunnel.command(name="ls")
def ls():
    """List active shares."""
    lines = _list_shares()
    if not lines:
        click.echo("No active shares (or the sidecar is down).")
        return
    click.echo("\n".join(lines))


@tunnel.command()
@click.argument("name", required=False, default=None)
def down(name):
    """Stop the tunnel sidecar (and its active shares)."""
    if name:
        name = validate_share_name(name)
        result = _zrok2_exec_capture(
            "agent", "release", "share", name, check=False
        )
        if result.returncode != 0:
            raise click.ClickException(
                "zrok2 agent release failed: "
                f"{(result.stderr or result.stdout).strip()}"
            )
        click.echo(f"Released share {name!r}.")
    click.echo("Stopping tunnel sidecar...")
    subprocess.run(_compose_cmd("stop", "tunnel"), check=True)
    click.echo("Tunnel stopped.")