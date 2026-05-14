"""Vault-backed cache for 1Password op:// references."""

import json
import os
import platform
import re
import subprocess
import urllib.error
import urllib.request
from typing import Optional

from cove import local_cache


VAULT_ADDR_DEFAULT = "http://127.0.0.1:8200"
VAULT_KV_MOUNT = "secret"
VAULT_OP_CACHE_PREFIX = "op-cache"
KEYSTORE_TOKEN_SERVICE = "cove/vault/root-token"


def parse_op_ref(ref: str) -> tuple[str, str, str]:
    if not ref.startswith("op://"):
        raise ValueError(f"Not an op:// reference: {ref!r}")
    parts = ref[len("op://") :].split("/")
    if len(parts) < 3:
        raise ValueError(f"op:// reference must have vault/item/field: {ref!r}")
    return parts[0], parts[1], "/".join(parts[2:])


def _slugify(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9_-]+", "-", s)
    s = re.sub(r"-+", "-", s)
    return s.strip("-")


def op_ref_to_vault_path(ref: str) -> str:
    vault, item, field = parse_op_ref(ref)
    return (
        f"{VAULT_KV_MOUNT}/data/{VAULT_OP_CACHE_PREFIX}"
        f"/{_slugify(vault)}/{_slugify(item)}/{_slugify(field)}"
    )


def _vault_addr() -> str:
    return os.environ.get("VAULT_ADDR", VAULT_ADDR_DEFAULT)


def _vault_token() -> str:
    tok = os.environ.get("VAULT_TOKEN")
    if tok:
        return tok
    user = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
    if platform.system() == "Darwin":
        cmd = [
            "security",
            "find-generic-password",
            "-a",
            user,
            "-s",
            KEYSTORE_TOKEN_SERVICE,
            "-w",
        ]
    else:
        cmd = [
            "secret-tool",
            "lookup",
            "service",
            KEYSTORE_TOKEN_SERVICE,
            "account",
            user,
        ]
    proc = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if proc.returncode != 0:
        raise RuntimeError(
            "No Vault token. Set VAULT_TOKEN or run bootstrap_vault.yml first.\n"
            f"Tried: {' '.join(cmd)}\n"
            f"stderr: {proc.stderr.strip()}"
        )
    return proc.stdout.strip()


def _vault_request(
    method: str, path: str, body: Optional[dict] = None, _allow_retry: bool = True
) -> tuple[int, dict]:
    url = f"{_vault_addr()}/v1/{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("X-Vault-Token", _vault_token())
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            content = resp.read().decode()
            return resp.status, (json.loads(content) if content else {})
    except urllib.error.HTTPError as e:
        if e.code == 503 and _allow_retry:
            from cove import vault_unseal

            vault_unseal.ensure_unsealed()
            return _vault_request(method, path, body, _allow_retry=False)
        content = e.read().decode()
        try:
            parsed = json.loads(content) if content else {}
        except json.JSONDecodeError:
            parsed = {"error": content}
        return e.code, parsed


def vault_get_cached(op_ref: str) -> Optional[str]:
    path = op_ref_to_vault_path(op_ref)
    status, body = _vault_request("GET", path)
    if status == 404:
        return None
    if status != 200:
        raise RuntimeError(f"Vault read failed at {path}: HTTP {status} {body}")
    return body.get("data", {}).get("data", {}).get("value")


def _vault_write(op_ref: str, value: str) -> None:
    path = op_ref_to_vault_path(op_ref)
    status, body = _vault_request(
        "POST",
        path,
        {
            "data": {"value": value, "op_ref": op_ref},
        },
    )
    if status not in (200, 204):
        raise RuntimeError(f"Vault write failed at {path}: HTTP {status} {body}")


def _op_read(op_ref: str) -> str:
    # On non-macOS try bare op first (works with service account tokens).
    if platform.system() != "Darwin":
        proc = subprocess.run(
            ["op", "read", "--no-newline", "--", op_ref],
            capture_output=True, text=True, stdin=subprocess.DEVNULL,
        )
        if proc.returncode == 0:
            return proc.stdout

    # Primary path (macOS and fallback): op run wraps in a single biometric prompt.
    proc = subprocess.run(
        ["op", "run", "--", "op", "read", "--no-newline", "--", op_ref],
        capture_output=True, text=True, stdin=subprocess.DEVNULL,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"op read failed for {op_ref}\nstderr: {proc.stderr.strip()}"
        )
    return proc.stdout


def vault_put_op_ref(op_ref: str, force_refresh: bool = False) -> str:
    if not force_refresh:
        local = local_cache.get(op_ref)
        if local is not None:
            return local
        try:
            cached = vault_get_cached(op_ref)
            if cached is not None:
                local_cache.put(op_ref, cached)
                return cached
        except RuntimeError:
            pass
    raise RuntimeError(
        f"{op_ref} is not cached locally or in Vault.\n"
        "Run 'cove creds batch-pull' first."
    )
