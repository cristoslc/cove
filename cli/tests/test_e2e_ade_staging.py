"""Tier 2 staging E2E for the ADE service through the ISOLATED staging stack.

Requires a deployed isolated staging stack (scripts/staging/deploy-isolated.sh,
then scripts/staging/e2e.sh). The stack is the parallel `cove-staging` compose
project: nginx on 127.0.0.1:9443 with the `ade.cove` Host header routing to the
bb server. The live cove stack is never touched.

Target URL comes from BB_STAGING_URL (default https://127.0.0.1:9443, the
e2e.sh default). TLS is the shared mkcert pair copied into the staging data
root; verification is off (self-signed in the generated-cert fallback).
"""

from __future__ import annotations

import base64
import os
import socket
import ssl

import pytest
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = os.environ.get("BB_STAGING_URL", "https://127.0.0.1:9443").rstrip("/")
ADE_HOST = "ade.cove"

pytestmark = pytest.mark.staging


def _get(path: str, host: str = ADE_HOST, **kw) -> requests.Response:
    return requests.get(
        f"{BASE_URL}{path}",
        headers={"Host": host},
        verify=False,
        timeout=30,
        **kw,
    )


def test_health_returns_ok_true():
    """GET /health with Host: ade.cove routes to bb; the payload reports ok."""
    r = _get("/health")
    assert r.status_code == 200, f"status {r.status_code}: {r.text[:200]}"
    body = r.json()
    assert body.get("ok") is True, f"health payload not ok: {body}"


def test_wrong_host_does_not_reach_bb():
    """The Host header selects the ade block: another vhost must not serve bb."""
    r = _get("/health", host="git.cove")
    served_bb = r.status_code == 200
    try:
        served_bb = served_bb and r.json() == {"ok": True}
    except ValueError:
        served_bb = False
    assert not served_bb, "git.cove vhost unexpectedly served the bb health payload"


def test_websocket_upgrade_returns_101():
    """The realtime channel upgrades through nginx: 101 Switching Protocols.

    bb's browser WS path needs standard upgrade headers only (no subprotocol,
    no cookie — spike 2). Raw socket + TLS keeps this dependency-free.
    """
    parsed_host, parsed_port = "127.0.0.1", 9443
    if BASE_URL.startswith("https://"):
        rest = BASE_URL[len("https://"):]
        if ":" in rest:
            parsed_host, parsed_port = rest.split(":", 1)
            parsed_port = int(parsed_port)
    raw = socket.create_connection((parsed_host, parsed_port), timeout=15)
    try:
        ctx = ssl._create_unverified_context()
        sock = ctx.wrap_socket(raw, server_hostname=ADE_HOST)
        key = base64.b64encode(os.urandom(16)).decode()
        request = (
            f"GET /ws HTTP/1.1\r\n"
            f"Host: {ADE_HOST}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            f"Origin: https://{ADE_HOST}\r\n"
            "\r\n"
        )
        sock.sendall(request.encode())
        status_line = sock.recv(4096).split(b"\r\n", 1)[0].decode(errors="replace")
        assert " 101 " in status_line, (
            f"expected 101 Switching Protocols, got: {status_line}"
        )
        sock.close()
    finally:
        raw.close()
