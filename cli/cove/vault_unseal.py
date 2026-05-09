"""Unseal a local Vault using OS-keystore Shamir keys."""

import json
import os
import platform
import subprocess
import urllib.error
import urllib.request
from typing import Optional

VAULT_ADDR_DEFAULT = "http://127.0.0.1:8200"
KEYSTORE_PREFIX = "cove/vault"
KEYSTORE_ACCOUNT = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
KEYSTORE_THRESHOLD = 3


def _vault_addr() -> str:
    return os.environ.get("VAULT_ADDR", VAULT_ADDR_DEFAULT)


def _read_keystore(service: str) -> str:
    if not KEYSTORE_ACCOUNT:
        raise RuntimeError("Cannot determine OS username: set $USER or $LOGNAME")
    if platform.system() == "Darwin":
        cmd = [
            "security",
            "find-generic-password",
            "-a",
            KEYSTORE_ACCOUNT,
            "-s",
            service,
            "-w",
        ]
    else:
        cmd = [
            "secret-tool",
            "lookup",
            "service",
            service,
            "account",
            KEYSTORE_ACCOUNT,
        ]
    proc = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if proc.returncode != 0:
        raise RuntimeError(f"Keystore read failed for {service}: {proc.stderr.strip()}")
    return proc.stdout.strip()


def _vault_post(path: str, body: Optional[dict] = None) -> tuple[int, dict]:
    url = f"{_vault_addr()}/{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            content = resp.read().decode()
            return resp.status, (json.loads(content) if content else {})
    except urllib.error.HTTPError as e:
        content = e.read().decode()
        parsed = json.loads(content) if content else {}
        return e.code, parsed
    except urllib.error.URLError as e:
        raise RuntimeError(f"Vault unreachable at {_vault_addr()}: {e.reason}")


def vault_health() -> dict:
    url = f"{_vault_addr()}/v1/sys/health"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req) as resp:
            content = resp.read().decode()
            return json.loads(content) if content else {}
    except urllib.error.HTTPError as e:
        content = e.read().decode()
        return json.loads(content) if content else {}
    except urllib.error.URLError as e:
        raise RuntimeError(f"Vault unreachable at {_vault_addr()}: {e.reason}")


def ensure_unsealed() -> dict:
    health = vault_health()
    initialized = health.get("initialized", False)
    sealed = health.get("sealed", True)

    if not initialized:
        raise RuntimeError("Vault is not initialized. Run bootstrap_vault.yml first.")

    if not sealed:
        return health

    status, _ = _vault_post("v1/sys/unseal", {"reset": True})
    if status not in (200, 204):
        raise RuntimeError(f"Failed to reset unseal progress: {status}")

    keys = []
    for i in range(1, KEYSTORE_THRESHOLD + 1):
        keys.append(_read_keystore(f"{KEYSTORE_PREFIX}/unseal-{i}"))

    for key in keys:
        status, body = _vault_post("v1/sys/unseal", {"key": key})
        if status not in (200, 204):
            raise RuntimeError(f"Unseal key rejected: {body}")

    health = vault_health()
    if health.get("sealed", True):
        raise RuntimeError("Vault still sealed after all unseal keys")

    return health
