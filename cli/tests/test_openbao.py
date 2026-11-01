"""OpenBao migration guardrails.

Cove's secrets server is OpenBao 2.7.x pinned by digest, served from the
compose service still named `vault`. These tests pin the parts a pin bump or a
careless compose edit would silently break: the image identity, the config
shape OpenBao needs (no `disable_mlock`, `/openbao` paths, `bao` healthcheck),
the non-root user override, and the keystore namespace override the rehearsal
and test lanes use so they never read or overwrite live unseal material.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_DIR = REPO_ROOT / "compose"


def _group_vars() -> dict:
    return yaml.safe_load((COMPOSE_DIR / "group_vars" / "all.yml").read_text())


def _compose() -> dict:
    return yaml.safe_load((COMPOSE_DIR / "docker-compose.yml").read_text())


def _vault_service() -> dict:
    return _compose()["services"]["vault"]


def test_pin_is_openbao_2_7_digest_pinned():
    gv = _group_vars()
    assert gv["vault_image_tag"].startswith("2.7."), "OpenBao 2.7.x is the ruling"
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", gv["vault_image_digest"])
    assert gv["vault_image"] == (
        "openbao/openbao:{{ vault_image_tag }}@{{ vault_image_digest }}"
    )
    # Service, hostname, and container name stay `vault` / `vault.cove` /
    # `cove-vault`: cert SANs, /etc/hosts, nginx, and the CLI's container
    # lookups all key off them.
    assert gv["vault_container_name"] == "cove-vault"


def test_compose_service_keeps_vault_name_and_openbao_shape():
    svc = _vault_service()
    assert svc["container_name"] == "${VAULT_CONTAINER_NAME:-cove-vault}"
    assert svc["image"].startswith("${VAULT_IMAGE:-openbao/openbao:2.7.")
    assert svc["command"] == ["server"]
    # mlock is gone from OpenBao 2.x; the capability and directive must not
    # be carried forward as if they still did something.
    assert "cap_add" not in svc
    # Non-root: run as the operator so the bind-mounted data dir stays
    # operator-owned, the same convention Forgejo uses.
    assert svc["user"] == "${VAULT_UID:-1000}:${VAULT_GID:-1000}"
    assert svc["environment"]["SKIP_CHOWN"] == "1"
    volumes = svc["volumes"]
    assert "${COVE_DATA_ROOT}/vault/data:/openbao/data" in volumes
    assert "${COVE_DATA_ROOT}/vault/logs:/openbao/logs" in volumes
    assert "./vault/vault.hcl:/openbao/config/vault.hcl:ro" in volumes
    assert svc["healthcheck"]["test"] == [
        "CMD",
        "bao",
        "status",
        "-address=http://127.0.0.1:8200",
    ]


def test_vault_hcl_is_openbao_compatible():
    raw = (COMPOSE_DIR / "vault" / "vault.hcl").read_text()
    # Comments may name the removed directive; the effective config must not.
    cfg = "\n".join(
        line for line in raw.splitlines() if not line.strip().startswith("#")
    )
    assert "disable_mlock" not in cfg, "obsolete in OpenBao 2.0; drop it"
    assert 'path    = "/openbao/data"' in cfg
    assert 'node_id = "cove-1"' in cfg
    assert 'address     = "0.0.0.0:8200"' in cfg
    assert 'tls_disable = "true"' in cfg
    assert "ui           = true" in cfg


def test_bringup_renders_vault_uid_gid():
    bringup = (COMPOSE_DIR / "bringup.yml").read_text()
    assert "VAULT_UID={{ ansible_user_uid }}" in bringup
    assert "VAULT_GID={{ ansible_user_gid }}" in bringup


def test_keystore_prefix_defaults_to_live_namespace(monkeypatch):
    from cove import constants

    monkeypatch.delenv("COVE_VAULT_KEYSTORE_PREFIX", raising=False)
    assert constants.vault_keystore_prefix() == "cove/vault"


def test_unseal_reads_scratch_keystore_when_overridden(monkeypatch):
    from cove import vault_unseal

    monkeypatch.setenv("COVE_VAULT_KEYSTORE_PREFIX", "cove/vault-rehearsal")
    read: list[str] = []
    monkeypatch.setattr(vault_unseal, "_read_keystore", read.append)
    monkeypatch.setattr(
        vault_unseal,
        "vault_health",
        lambda timeout=None: {"initialized": True, "sealed": True},
    )
    monkeypatch.setattr(vault_unseal, "_vault_post", lambda path, body=None: (200, {}))
    # ensure_unsealed re-reads health at the end and requires sealed=false.
    health = iter(
        [{"initialized": True, "sealed": True}, {"initialized": True, "sealed": False}]
    )
    monkeypatch.setattr(vault_unseal, "vault_health", lambda timeout=None: next(health))

    vault_unseal.ensure_unsealed()

    assert read == [
        "cove/vault-rehearsal/unseal-1",
        "cove/vault-rehearsal/unseal-2",
        "cove/vault-rehearsal/unseal-3",
    ]


def test_vault_cache_token_reads_scratch_keystore_when_overridden(monkeypatch):
    from cove import vault_cache

    monkeypatch.delenv("VAULT_TOKEN", raising=False)
    monkeypatch.setenv("COVE_VAULT_KEYSTORE_PREFIX", "cove/vault-rehearsal")
    monkeypatch.setattr(vault_cache.platform, "system", lambda: "Darwin")

    seen: dict = {}

    class _Proc:
        returncode = 0
        stdout = "token-from-scratch\n"
        stderr = ""

    def _run(cmd, **kwargs):
        seen["cmd"] = cmd
        return _Proc()

    monkeypatch.setattr(vault_cache.subprocess, "run", _run)

    assert vault_cache._vault_token() == "token-from-scratch"
    service_index = seen["cmd"].index("-s") + 1
    assert seen["cmd"][service_index] == "cove/vault-rehearsal/root-token"


def test_status_reports_standby_instead_of_connection_refused(monkeypatch):
    from cove import status

    class _Resp:
        status_code = 429

    monkeypatch.setattr(status.requests, "get", lambda *a, **k: _Resp())

    result = status._check_vault()

    assert result.ok is False
    assert result.detail == "initialized, standby"


def test_service_doc_exists():
    doc = REPO_ROOT / "docs" / "services" / "openbao.md"
    assert doc.is_file(), "OpenBao is a core service and needs a service doc"
    assert "rollback" in doc.read_text().lower()
