"""CLI commands for the Bifrost gateway lifecycle.

LiteLLM replacement candidate, ADDITIVE phase (docs/musings/litellm-exit.md):
`cove bifrost` manages the bifrost compose profile alongside the live
litellm services — nothing is removed and no client is re-pointed by this
module (the client-facing re-point is a later, workstation-lane-gated phase).
"""

import base64
import json
import os
import secrets
import sqlite3
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import click

from cove.constants import NGINX_HTTPS_PORT
from cove.stateless import (
    resolve_compose_dir,
    ensure_compose_source_ready,
    _config_compose_dir,
)
from cove.credential_env import (
    credential_from_ambient,
    resolve_data_root,
    scrubbed_environment,
)
# Shared 4-word passphrase helper (speedtest's admin password generator);
# importing keeps a single source of truth for the wordlist.
from cove.speedtest import _passphrase as _friendly_passphrase


BIFROST_URL = "https://bifrost.cove.local/"
BIFROST_OP_VAULT = "Private"
BIFROST_ITEM_TITLE = "Bifrost Gateway"
# The shared Cove admin identity (ADR-017) lives in a cove.local-keyed item,
# NOT a per-service item. Encryption key and dashboard password live in the
# Bifrost Gateway item; the admin username comes from the shared Cove Admin
# item. The CLIENT virtual key is NOT a cove-generated credential: Bifrost
# v2.3.x generates virtual-key tokens itself (sk-bf-...) and ignores any
# value provided at seed time, so `cove bifrost up` FETCHES the generated
# token from the gateway's admin API after boot and projects it into the
# compose .env as BIFROST_CLIENT_VIRTUAL_KEY.
COVE_ADMIN_ITEM_TITLE = "Cove Admin"
ENCRYPTION_KEY_OP_REF = f"op://{BIFROST_OP_VAULT}/{BIFROST_ITEM_TITLE}/encryption_key"
ADMIN_PASSWORD_OP_REF = f"op://{BIFROST_OP_VAULT}/{BIFROST_ITEM_TITLE}/admin_password"
ADMIN_USERNAME_OP_REF = f"op://{BIFROST_OP_VAULT}/{COVE_ADMIN_ITEM_TITLE}/username"
CLIENT_VIRTUAL_KEY_ENV = "BIFROST_CLIENT_VIRTUAL_KEY"


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
    return resolve_data_root(_compose_env_path())


def _generate_encryption_key() -> str:
    # 32 random bytes, hex-encoded → 64 chars; Bifrost derives its
    # at-rest/config-store encryption key from this value.
    return secrets.token_hex(32)


def _seed_example_path():
    return resolve_compose_dir() / "seeds" / "bifrost-creds.yaml.example"


def _render_seed() -> str:
    """Render the bifrost seed template into a shared, URL-keyed 1Password
    item (title 'Bifrost Gateway' keyed to `https://bifrost.cove.local/`),
    so the same credentials work on all the operator's machines.

    The item holds the config-store encryption key and the dashboard admin
    password. The admin USERNAME comes from the shared 'Cove Admin' item
    (https://cove.local/, ADR-017). The CLIENT virtual key is not held here:
    Bifrost v2.3.x generates virtual-key tokens itself and ignores any value
    provided at seed time, so `cove bifrost up` fetches the generated token
    from the gateway's admin API after boot and projects it into the compose
    .env (BIFROST_CLIENT_VIRTUAL_KEY).

    Each field carries its own placeholder so the values are always
    distinct:"""
    template = _seed_example_path().read_text()
    rendered = template
    rendered = rendered.replace("{{generate:encryption_key}}", _generate_encryption_key())
    rendered = rendered.replace("{{generate:admin_password}}", _friendly_passphrase())
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
    # 1. Operator explicitly opted into the ambient value — honor directly.
    #    Without COVE_ALLOW_AMBIENT_CREDENTIALS the files of record are the only
    #    inputs (a divergent ambient value is reported, never silently kept).
    explicit = credential_from_ambient(env_key, _compose_env_path().parent)
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
    """Provision the Bifrost dashboard credentials into the compose .env,
    reusing the shared 1Password items across machines. Also injects the
    shared Cove Admin username (dashboard identity). Never prints a secret
    value. The client virtual key is NOT provisioned here: Bifrost
    generates it (see CLIENT_VIRTUAL_KEY_ENV)."""
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
    - local.env: 0600; provider keys are projected in later (see
      _ensure_synthetic_key), operator edits preserved; never overwritten
      wholesale.
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


def _runtime_env_path() -> Path:
    """The compose .env of the DEPLOYED stack: the authoritative runtime
    credential context (status reads, provider-key pass-through checks).

    Status commands may run before provisioning and from a source checkout
    or worktree, whose compose dir carries no runtime credentials. The
    canonical install dir is where the wheel deploys compose resources and
    where the workstation lane projects SOPS entries, so reads prefer it.
    An explicit COVE_COMPOSE_DIR (tests, sandbox) always wins."""
    explicit = os.environ.get("COVE_COMPOSE_DIR")
    if explicit:
        return Path(explicit) / ".env"
    installed = _config_compose_dir()
    if (installed / "inventory.yml").exists():
        return installed / ".env"
    return resolve_compose_dir() / ".env"


def _runtime_data_root() -> Path:
    """Data root of the DEPLOYED stack: explicit COVE_DATA_ROOT wins (same
    precedence as _cove_data_root), then the deployed compose .env, then the
    canonical default."""
    return resolve_data_root(_runtime_env_path())


def _env_flag_set(env_key: str) -> bool:
    """TRUE when the DEPLOYED compose .env has KEY=<non-empty>. Values are
    never echoed."""
    env_path = _runtime_env_path()
    if not env_path.exists():
        return False
    for line in env_path.read_text().splitlines():
        if line.startswith(f"{env_key}="):
            return bool(line.split("=", 1)[1].strip())
    return False


def _local_env_flag_set(name: str) -> bool:
    """TRUE when the bifrost local.env carries NAME=<non-empty>."""
    env_file = _runtime_data_root() / "bifrost" / "local.env"
    if not env_file.exists():
        return False
    for line in env_file.read_text().splitlines():
        if line.startswith(f"{name}="):
            return bool(line.split("=", 1)[1].strip())
    return False


def _read_file_var(env_file: Path, name: str) -> str | None:
    """In-process single read of NAME= from an env file. Never prints."""
    if not env_file.exists():
        return None
    for line in env_file.read_text().splitlines():
        if line.startswith(f"{name}="):
            value = line.split("=", 1)[1].strip()
            return value or None
    return None


def _upsert_local_env(name: str, value: str) -> None:
    """Set NAME=VALUE in the bifrost local.env idempotently (no duplicate
    lines). Values are never echoed, mode stays 0600."""
    env_file = _cove_data_root() / "bifrost" / "local.env"
    env_file.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    if env_file.exists():
        for existing in env_file.read_text().splitlines():
            if existing.startswith(f"{name}="):
                continue
            lines.append(existing)
    lines.append(f"{name}={value}")
    env_file.write_text("\n".join(lines) + "\n")
    env_file.chmod(0o600)


def _ensure_synthetic_key() -> None:
    """Project the Synthetic provider key into the bifrost local.env.

    One key, one source of record: the LiteLLM local.env is the deployed
    env LiteLLM's own provider config already runs on, so the projection
    copies from there in-process (same 1Password-sourced value, zero new
    custody artifacts). Precedence: explicit SYNTHETIC_API_KEY env >
    an existing bifrost local.env entry > the litellm local.env projection.
    Fail loud when no source exists; the key is the subscription hop's
    credential, the gateway is degraded without it. Never prints."""
    explicit = credential_from_ambient(
        "SYNTHETIC_API_KEY", _compose_env_path().parent
    )
    if explicit:
        _upsert_local_env("SYNTHETIC_API_KEY", explicit)
        return

    if _local_env_flag_set("SYNTHETIC_API_KEY"):
        return

    litellm_env = _cove_data_root() / "litellm" / "local.env"
    projected = _read_file_var(litellm_env, "SYNTHETIC_API_KEY")
    if projected:
        _upsert_local_env("SYNTHETIC_API_KEY", projected)
        click.echo(
            "Projected SYNTHETIC_API_KEY from the LiteLLM local.env "
            "(same source of record, value never printed)."
        )
        return

    raise click.ClickException(
        "SYNTHETIC_API_KEY is missing. The deployed LiteLLM local.env "
        f"({litellm_env}) is the source of record for the Synthetic "
        "subscription key. Copy the key into that file (or set "
        "SYNTHETIC_API_KEY together with COVE_ALLOW_AMBIENT_CREDENTIALS=1 to "
        "opt into the ambient environment) and re-run `cove bifrost up`."
    )


def _check_ollama_passthrough() -> None:
    """Warn loudly when the workstation lane's SOPS projection has not
    landed OLLAMA_API_KEY in the compose .env. Non-fatal by design: cove
    holds no custody of this key (2026-10-26 ruling) and the ollama-cloud
    hop degrades to upstream 401s, it does not break the gateway."""
    if not _env_flag_set("OLLAMA_API_KEY"):
        click.echo(
            "WARNING: OLLAMA_API_KEY is absent from the deployed compose "
            ".env — the workstation lane projects it there (SOPS). The "
            "ollama-cloud ladder hop will fail upstream until it lands; "
            "continuing."
        )


def _gateway_port() -> int:
    """The container port Bifrost listens on, from the deployed .env
    (default 4002, the compose default)."""
    raw = _read_file_var(_runtime_env_path(), "BIFROST_PORT")
    try:
        return int(raw or "4002")
    except ValueError:
        return 4002


def _wait_for_gateway_health(port: int, timeout_s: int = 90) -> bool:
    """Poll http://127.0.0.1:<port>/health (direct loopback container port,
    no nginx or TLS in the way) until it answers 200."""
    deadline = time.monotonic() + timeout_s
    url = f"http://127.0.0.1:{port}/health"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        time.sleep(2)
    return False


def _fetch_client_virtual_key(port: int, username: str, password: str) -> dict:
    """GET /api/governance/virtual-keys over the direct loopback port with
    the dashboard Basic credentials. Returns the vk-cove row (the secret
    travels in-process only). Raises ClickException on any failure."""
    url = f"http://127.0.0.1:{port}/api/governance/virtual-keys"
    req = urllib.request.Request(url, headers={
        "Authorization": "Basic " + base64.b64encode(
            f"{username}:{password}".encode()).decode(),
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise click.ClickException(
            f"Failed to fetch the generated client virtual key from the "
            f"gateway admin API (HTTP {e.code})."
        )
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise click.ClickException(
            f"Failed to reach the gateway admin API at {url}: {e}"
        )
    rows = [row for row in data.get("virtual_keys", []) if row.get("id") == "vk-cove"]
    value = rows[0].get("value") if rows else None
    if not value:
        raise click.ClickException(
            "The generated client virtual key (vk-cove) was not found in "
            "the gateway's governance store; `cove bifrost up` seeds it on "
            "first boot — re-run `cove bifrost up`."
        )
    return rows[0]


def _ensure_client_virtual_key() -> str:
    """Fetch Bifrost's generated client token and project it into the
    compose .env. Bifrost v2.3.x generates virtual-key tokens itself
    (ignoring any seed-provided value), so the ONLY honest source is the
    gateway's own admin API. Idempotent: the store is durable (mounted
    config.db), so the token is stable across restarts and recreations;
    an operator rotation via the dashboard is picked up on the next
    `cove bifrost up`. Never prints the value."""
    env_path = _runtime_env_path()
    # The stored token must exist on the durable store; fetch + project.
    username = _read_file_var(env_path, "BIFROST_ADMIN_USERNAME")
    password = _read_file_var(env_path, "BIFROST_ADMIN_PASSWORD")
    if not username or not password:
        raise click.ClickException(
            "BIFROST_ADMIN_USERNAME / BIFROST_ADMIN_PASSWORD are missing "
            "from the compose .env; run `cove bifrost up` (provisioning "
            "happens before the gateway starts)."
        )
    port = _gateway_port()
    if not _wait_for_gateway_health(port):
        raise click.ClickException(
            "The Bifrost gateway did not pass /health within 90s; check "
            "`cove bifrost logs`."
        )
    row = _fetch_client_virtual_key(port, username, password)
    _upsert_env(CLIENT_VIRTUAL_KEY_ENV, row["value"])
    click.echo(
        "Client virtual key projected into the compose .env "
        f"({CLIENT_VIRTUAL_KEY_ENV}; Bifrost-generated sk-bf- token, "
        "value never printed). Rotate via the dashboard or the governance "
        "API; the projection refreshes on the next `cove bifrost up`."
    )
    return row["value"]


def _neutral_endpoint_upstream() -> str | None:
    """The active proxy upstream the neutral llmproxy.cove vhost proxies to,
    read from the deployed nginx config — the one-line product-swap point
    (docs/services/bifrost.md, "Client endpoint").

    Returns None when the deployed config is absent or carries no
    llmproxy_upstream line (reported, never guessed)."""
    conf = resolve_compose_dir() / "nginx" / "default.conf"
    if not conf.exists():
        return None
    for line in conf.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("set $llmproxy_upstream "):
            return (
                stripped.removeprefix("set $llmproxy_upstream ")
                .rstrip(";")
                .strip()
            )
    return None


def _neutral_endpoint_backend_key_state() -> str | None:
    """Whether the deployed edge config carries a backend key for the ACTIVE
    upstream: "SET", "missing", or None when the deployed edge config is
    absent (reported, never guessed). Names/states only — never the value."""
    compose = resolve_compose_dir()
    conf = compose / "nginx" / "llmproxy-auth.conf"
    if not conf.exists():
        return None
    upstream = _neutral_endpoint_upstream()
    if not upstream:
        return None
    prefix = f'"{upstream}"'
    for line in conf.read_text().splitlines():
        stripped = line.strip()
        if not stripped.startswith(prefix):
            continue
        value = stripped[len(prefix):].strip().rstrip(";").strip().strip('"')
        if not value.startswith("Bearer "):
            return "missing"
        return "SET" if value[len("Bearer "):].strip() else "missing"
    return "missing"


def _probe_health_code(host: str) -> int | None:
    """HTTP status of GET /health through nginx for one hostname (SNI-free
    curl with an explicit Host header), or None when the probe itself
    failed (timeout, connection refused, TLS/hostname dead)."""
    try:
        health = subprocess.run(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
             "-H", f"Host: {host}",
             f"https://127.0.0.1:{NGINX_HTTPS_PORT}/health"],
            capture_output=True, text=True, timeout=10,
        )
    except subprocess.TimeoutExpired:
        return None
    if health.returncode != 0:
        return None
    try:
        return int(health.stdout.strip())
    except ValueError:
        return None


def _classify_health(code: int | None) -> str:
    """Classify a /health probe result: "ok" (2xx/3xx), "auth-gated"
    (401/403 — the service answered and requires a credential; auth is a
    separate question from reachability), or "unreachable" (probe failed,
    4xx-other, or 5xx). LiteLLM answers /health with 401 when its master
    key is absent from the probe; Bifrost with governance enabled can do
    the same — neither is an outage."""
    if code is None:
        return "unreachable"
    if code in (401, 403):
        return "auth-gated"
    if 200 <= code < 400:
        return "ok"
    return "unreachable"


_HEALTH_LABELS = {"ok": "OK", "auth-gated": "OK (auth-gated)",
                  "unreachable": "UNREACHABLE"}


def _probe_health_hosts(hosts: tuple[str, ...]) -> tuple[int | None, str]:
    """Probe /health across the given hostnames (nginx vhosts), returning
    the best (code, classification): any 2xx/3xx wins over an auth-gated
    answer, which wins over unreachable."""
    best_code: int | None = None
    best = "unreachable"
    for host in hosts:
        code = _probe_health_code(host)
        verdict = _classify_health(code)
        if verdict == "ok":
            return code, verdict
        if verdict == "auth-gated":
            best_code, best = code, verdict
    return best_code, best


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
    _ensure_synthetic_key()
    _check_ollama_passthrough()
    click.echo("Starting Bifrost gateway (profile: bifrost)...")
    subprocess.run(
        _compose_cmd("--profile", "bifrost", "up", "-d", "--build"),
        check=True,
        env=scrubbed_environment(resolve_compose_dir()),
    )
    _ensure_client_virtual_key()
    click.echo(f"Bifrost gateway is running. Gateway: {BIFROST_URL}")


@bifrost.command()
def down():
    """Stop the Bifrost gateway and its egress sinkhole."""
    ensure_compose_source_ready(resolve_compose_dir())
    click.echo("Stopping Bifrost gateway...")
    subprocess.run(
        _compose_cmd("stop", "bifrost", "bifrost-dns"),
        check=True,
        env=scrubbed_environment(resolve_compose_dir(), warn=False),
    )
    click.echo("Bifrost gateway stopped.")


@bifrost.command()
def status():
    """Check Bifrost gateway health and credential wiring."""
    result = subprocess.run(
        _compose_cmd("ps", "--format", "table {{.Name}}\t{{.Status}}\t{{.Ports}}"),
        capture_output=True, text=True,
        env=scrubbed_environment(resolve_compose_dir(), warn=False),
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
                "BIFROST_ADMIN_PASSWORD", CLIENT_VIRTUAL_KEY_ENV):
        state = "SET" if _env_flag_set(key) else "missing"
        suffix = " (Bifrost-generated, dashboard/API rotates it)" \
            if key == CLIENT_VIRTUAL_KEY_ENV else ""
        click.echo(f"  {key}: {state}{suffix}")

    click.echo("Checking /health through nginx...")
    surfaces = (
        ("Bifrost gateway", ("bifrost.cove.local", "bifrost.cove")),
        ("Neutral client endpoint (llmproxy.cove)",
         ("llmproxy.cove.local", "llmproxy.cove")),
    )
    all_ok = True
    for label, hosts in surfaces:
        code, verdict = _probe_health_hosts(hosts)
        suffix = f" (HTTP {code})" if verdict not in ("ok",) and code is not None else ""
        click.echo(f"  {label}: " + _HEALTH_LABELS[verdict] + suffix)
        all_ok = all_ok and verdict in ("ok", "auth-gated")
    upstream = _neutral_endpoint_upstream()
    if upstream:
        click.echo(f"  llmproxy.cove upstream: {upstream}")
    else:
        click.echo(
            "  llmproxy.cove upstream: not found in deployed nginx config"
        )
    # The auth model, in one line: clients hold ONE cove-owned edge token; the
    # ACTIVE backend credential is injected server-side and never leaves the
    # edge, so a proxy swap cannot strand a client credential.
    click.echo(
        "  llmproxy.cove edge auth: clients authenticate at the edge with the "
        "cove-owned client token; backend credentials never reach clients"
    )
    key_state = _neutral_endpoint_backend_key_state()
    if key_state is None:
        click.echo(
            "  llmproxy.cove backend key: not found in deployed edge config"
        )
    else:
        click.echo(
            f"  llmproxy.cove backend key: {key_state} (injected server-side)"
        )
    if not all_ok:
        raise SystemExit(1)


@bifrost.command()
@click.option("-n", "--lines", default=50, help="Number of lines to show.")
@click.option("-f", "--follow", is_flag=True, help="Follow log output.")
def logs(lines, follow):
    """Tail Bifrost gateway logs."""
    cmd = _compose_cmd("logs", "--tail", str(lines))
    if follow:
        cmd.append("--follow")
    subprocess.run(
        cmd, check=True, env=scrubbed_environment(resolve_compose_dir(), warn=False)
    )