"""Tier 2 staging E2E for the ToolHive MCP gateway through the ISOLATED staging stack.

Requires a deployed isolated staging stack with the `mcp` profile
(scripts/staging/deploy-isolated.sh starts it when the branch's compose
declares it; then scripts/staging/e2e.sh). The stack is the parallel
`cove-staging` compose project: nginx on 127.0.0.1:9443 with the `mcp.cove`
Host header routing to the ToolHive control plane. The live cove stack is
never touched.

Phase-1 auth posture (docs/plans/toolhive-mcp-gateway.md): the vhost answers
/health only (proxied behind the private-range ACL) and returns 403 for every
other path — the unauthenticated management API/UI is not exposed until
Phase 2 opens it behind an auth layer.

Target URL comes from BB_STAGING_URL (default https://127.0.0.1:9443, the
e2e.sh default). TLS is the shared mkcert pair copied into the staging data
root; verification is off (self-signed in the generated-cert fallback). Like
test_e2e_ade_staging.py there is no silent skip: with no deployed stack these
tests fail loudly on connection errors.
"""

from __future__ import annotations

import os

import pytest
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = os.environ.get("BB_STAGING_URL", "https://127.0.0.1:9443").rstrip("/")
MCP_HOST = "mcp.cove"

pytestmark = pytest.mark.staging


def _get(path: str, host: str = MCP_HOST, **kw) -> requests.Response:
    return requests.get(
        f"{BASE_URL}{path}",
        headers={"Host": host},
        verify=False,
        timeout=30,
        **kw,
    )


def test_health_route_answers():
    """GET /health with Host: mcp.cove proxies to the ToolHive API health.

    ToolHive's healthy signal is HTTP 204 No Content (empty body) — the same
    signal `cove toolhive status` accepts via `curl -sf`.
    """
    r = _get("/health")
    assert r.status_code == 204, f"status {r.status_code}: {r.text[:200]}"


def test_management_api_returns_403():
    """Phase-1 posture: the management API is NOT exposed through mcp.cove.

    /api/v1beta/workloads is the ToolHive management surface; through this
    vhost nginx must return 403 for everything except /health.
    """
    r = _get("/api/v1beta/workloads")
    assert r.status_code == 403, f"status {r.status_code}: {r.text[:200]}"


def test_wrong_host_does_not_reach_toolhive():
    """The Host header selects the mcp.cove block: another vhost must not serve it."""
    r = _get("/health", host="git.cove")
    # ToolHive /health answers 204; git.cove (Forgejo in staging) must not.
    served_toolhive = r.status_code == 204
    assert not served_toolhive, (
        "git.cove vhost unexpectedly served the toolhive health route"
    )