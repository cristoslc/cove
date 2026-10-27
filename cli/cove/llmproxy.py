"""Credentials for the `llmproxy.cove` authentication edge.

`llmproxy.cove` is the ONE stable client-facing LLM endpoint (see
docs/services/bifrost.md, "Client endpoint"). It is also the authentication
edge:

* Clients hold a single cove-owned CLIENT TOKEN and nothing else. It is scoped
  to the edge and outlives any backend swap, so a LiteLLM -> Bifrost cutover
  never touches client config.
* The edge injects the ACTIVE backend credential toward the upstream (the
  LiteLLM master key today, the Bifrost virtual key after the flip). Backend
  credentials never reach clients.

This module owns the client token: resolve it from the operator override, the
compose `.env`, or the Vault/1Password cache, and provision it into 1Password
(a shared, URL-keyed `Cove LLM Proxy Client Key` item) when absent. The value
is never printed and never written to the compose `.env` by this module; the
rendered nginx config carries it at mode 0600.

The backend keys are read from the compose `.env` at up time: `LITELLM_MASTER_KEY`
(owned by `cove litellm`) and `BIFROST_CLIENT_VIRTUAL_KEY` (projected by
`cove bifrost up`).
"""

import atexit
import os
import secrets
import subprocess
import tempfile
from pathlib import Path

import click
import yaml

from cove.stateless import resolve_compose_dir


LLMPROXY_OP_VAULT = "Private"
LLMPROXY_ITEM_TITLE = "Cove LLM Proxy Client Key"
CLIENT_KEY_FIELD = "client_key"
# Shared across the operator's machines (URL-keyed item, ADR-017 pattern) —
# NOT per-hostname: the token is the same stable client credential everywhere.
CLIENT_KEY_OP_REF = (
    f"op://{LLMPROXY_OP_VAULT}/{LLMPROXY_ITEM_TITLE}/{CLIENT_KEY_FIELD}"
)

# Operator override for the client token (CI/staging/explicit pin).
CLIENT_KEY_ENV = "COVE_LLM_PROXY_CLIENT_KEY"
# Backend credentials, read from the compose .env at render time only.
LITELLM_KEY_ENV = "LITELLM_MASTER_KEY"
BIFROST_KEY_ENV = "BIFROST_CLIENT_VIRTUAL_KEY"

# Token prefix keeps OpenAI-compatible client libraries that validate a key
# shape happy; the value is a random 32-byte urlsafe token.
CLIENT_KEY_PREFIX = "sk-cove-"


def _compose_env_path() -> Path:
    return resolve_compose_dir() / ".env"


def _seed_example_path() -> Path:
    return resolve_compose_dir() / "seeds" / "llmproxy-creds.yaml.example"


def _generate_client_key() -> str:
    return CLIENT_KEY_PREFIX + secrets.token_urlsafe(32)


def _render_seed() -> str:
    """Render the seed template into the shared, URL-keyed 1Password item.

    The `{{generate:client_key}}` placeholder is replaced here (never passed
    through to `1p-bulk-write`, whose placeholder grammar is an integer
    length)."""
    template = _seed_example_path().read_text()
    return template.replace("{{generate:client_key}}", _generate_client_key())


def _seed_path() -> str:
    """Write the rendered seed to a temp file for 1p-bulk-write. The caller
    MUST unlink the returned path after use."""
    fd, path_str = tempfile.mkstemp(prefix="cove-llmproxy-seed-", suffix=".yaml")
    with os.fdopen(fd, "w") as f:
        f.write(_render_seed())
    return path_str


def _run_cove_creds(*args: str):
    """Run `cove creds ...`, capturing stdout (masked, never printed)."""
    return subprocess.run(
        ["cove", "creds", *args],
        capture_output=True, text=True, stdin=subprocess.DEVNULL,
        check=False,
    )


def _cached_client_key() -> str | None:
    """The cached client token (local file cache first, then Vault), or None.

    `cove creds vault-get` is cache-only: it never prompts and never reads
    1Password, so a warm machine converges without biometric interaction."""
    result = _run_cove_creds("vault-get", CLIENT_KEY_OP_REF)
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _provision_client_key() -> str:
    """Create the shared 1Password item, cache it, and return the value.

    Fail loud on every incomplete step: a token that exists in-process but not
    in 1Password would be unrecoverable after the next converge."""
    seed_path = _seed_path()
    try:
        write = _run_cove_creds("1p-bulk-write", seed_path, "--execute")
        if write.returncode != 0:
            raise click.ClickException(
                "The llmproxy.cove client token is missing and could not be "
                "provisioned: writing the shared 'Cove LLM Proxy Client Key' "
                "1Password item failed. Run `cove creds batch-pull` and retry "
                "`cove up` with 1Password unlocked.\n"
                f"stderr: {write.stderr.strip()}"
            )
        from cove import vault_cache

        try:
            value = vault_cache.vault_put_op_ref(CLIENT_KEY_OP_REF)
        except (ValueError, RuntimeError) as e:
            raise click.ClickException(
                "The llmproxy.cove client token was written to 1Password but "
                f"could not be cached in Vault: {e}. Retry `cove up`."
            )
    finally:
        os.unlink(seed_path)
    if not value:
        raise click.ClickException(
            f"{CLIENT_KEY_OP_REF} resolved to an empty value; the llmproxy "
            "edge will not render an empty client token."
        )
    return value


def ensure_client_key() -> str:
    """Return the cove-owned llmproxy client token, provisioning it if absent.

    Precedence: explicit `COVE_LLM_PROXY_CLIENT_KEY` (operator pin), the
    compose `.env` entry of the same name, the Vault/1Password cache, then
    create the shared 1Password item.

    Never prints the value."""
    explicit = os.environ.get(CLIENT_KEY_ENV)
    if explicit:
        return explicit
    env_path = _compose_env_path()
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith(f"{CLIENT_KEY_ENV}="):
                value = line.split("=", 1)[1].strip().strip("\"'")
                if value:
                    return value
    cached = _cached_client_key()
    if cached:
        return cached
    return _provision_client_key()


def _env_value(key: str) -> str:
    """A backend credential from the process env, then the compose `.env`."""
    explicit = os.environ.get(key)
    if explicit:
        return explicit
    env_path = _compose_env_path()
    if not env_path.exists():
        return ""
    for line in env_path.read_text().splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip().strip("\"'")
    return ""


def edge_secret_vars() -> dict[str, str]:
    """The three values the edge templates render.

    * `llmproxy_client_key` — cove-owned client token (required).
    * `llmproxy_litellm_key` / `llmproxy_bifrost_key` — the backend
      credentials the map pairs with `$llmproxy_upstream`. Empty when the
      respective service has never been provisioned; an empty backend key
      fails closed at the upstream and is never a client credential.
    """
    return {
        "llmproxy_client_key": ensure_client_key(),
        "llmproxy_litellm_key": _env_value(LITELLM_KEY_ENV),
        "llmproxy_bifrost_key": _env_value(BIFROST_KEY_ENV),
    }


def edge_secret_vars_file() -> Path:
    """Write the edge credentials to a 0600 Ansible extra-vars file.

    Ansible renders the nginx templates from these vars. Keeping them out of
    argv (where `ps` would expose them) and out of the compose `.env` (which
    the backend services own) is the point. The caller owns the returned path;
    it is also removed at process exit.
    """
    fd, path_str = tempfile.mkstemp(prefix="cove-llmproxy-edge-", suffix=".yml")
    path = Path(path_str)
    with os.fdopen(fd, "w") as f:
        yaml.safe_dump(edge_secret_vars(), f)
    path.chmod(0o600)
    atexit.register(lambda: path.unlink(missing_ok=True))
    return path
