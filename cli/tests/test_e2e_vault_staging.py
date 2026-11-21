"""Tier 2 staging E2E for the Vault boundary of the isolated staging stack.

The isolated stack (`scripts/staging/deploy-isolated.sh`) never runs Ansible.
It starts the `vault` compose service (OpenBao) with a fresh data directory,
but it does not initialize, unseal, or seed it, and it stores no unseal keys in
the OS keystore. That is deliberate: staging selects option 2 of the staging
decision, "make the vault dependency optional", because the only KV entries the
live stack reads are a 1Password-backed credential cache and seeding them would
drag the whole provisioning path into staging.

This module makes the boundary executable instead of leaving it implicit:

- `vault.cove` routes through the staging ingress to OpenBao, and
- OpenBao answers as uninitialized and sealed.

If staging ever gains a provisioned vault (option 1), this test fails on
purpose: change it and `docs/guides/staging.md` together. A future test that
genuinely needs a KV entry must skip with a named reason (what was missing and
how to enable it), never assert against a half-provisioned vault.

Target URL comes from BB_STAGING_URL (default https://127.0.0.1:9443).
"""

from __future__ import annotations

import os

import pytest
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = os.environ.get("BB_STAGING_URL", "https://127.0.0.1:9443").rstrip("/")
VAULT_HOST = "vault.cove"

pytestmark = pytest.mark.staging


def _get(path: str, host: str = VAULT_HOST) -> requests.Response:
    return requests.get(
        f"{BASE_URL}{path}",
        headers={"Host": host},
        verify=False,
        timeout=30,
    )


def _health() -> dict:
    r = _get("/v1/sys/health")
    # OpenBao answers 501 for an uninitialized instance and 503 while sealed;
    # anything else means the ingress or the service is broken, not "sealed".
    assert r.status_code in (200, 429, 472, 473, 501, 503), (
        f"vault.cove did not reach OpenBao: status {r.status_code}: "
        f"{r.text[:200]}"
    )
    try:
        return r.json()
    except ValueError:
        pytest.fail(
            "vault.cove did not return an OpenBao health document; "
            f"got status {r.status_code}: {r.text[:200]}"
        )


def test_vault_vhost_routes_to_openbao():
    """The staging ingress proxies vault.cove to the OpenBao service."""
    body = _health()
    assert "initialized" in body and "sealed" in body, (
        f"unexpected OpenBao health payload: {body}"
    )


def test_staging_vault_is_intentionally_uninitialized():
    """Option 2: staging leaves OpenBao uninitialized and carries no KV data.

    This is the contract, not an accident. A fresh staging root must not
    inherit live unseal keys, and no tier-2 test may depend on Vault KV.
    """
    body = _health()
    assert body.get("initialized") is False, (
        "staging OpenBao is initialized. Isolated staging selects option 2 "
        "(vault dependency optional) and must not initialize or seed it. "
        "If option 1 landed, update this test and docs/guides/staging.md."
    )
    assert body.get("sealed") is True, (
        "staging OpenBao reports sealed=false while uninitialized; "
        f"health payload: {body}"
    )
