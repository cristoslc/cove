"""One setting names the 1Password vault for every reference.

Service accounts cannot read Private, so the vault name is install state. The
CLI and the Ansible vars must read the same variable, or the references and the
provisioning plays would disagree after a vault move.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import yaml


def _reload(monkeypatch, value: str | None):
    from cove import creds

    if value is None:
        monkeypatch.delenv("COVE_OP_VAULT", raising=False)
    else:
        monkeypatch.setenv("COVE_OP_VAULT", value)
    importlib.reload(creds)
    return creds


def test_the_default_vault_is_private(monkeypatch):
    creds = _reload(monkeypatch, None)
    assert creds.OP_VAULT == "Private"
    assert creds.OP_REFS["cove_admin_password"] == "op://Private/Cove Admin/password"
    assert creds.OP_REFS["forgejo_admin"].startswith("op://Private/Forgejo ")


def test_the_variable_moves_every_reference(monkeypatch):
    creds = _reload(monkeypatch, "Cove Ops")
    assert creds.OP_VAULT == "Cove Ops"
    for key, ref in creds.OP_REFS.items():
        assert ref.startswith("op://Cove Ops/"), f"{key} still names another vault: {ref}"
    # placeholders survive for the callers that fill them
    assert "{hostname}" in creds.OP_REFS["forgejo_admin"]
    _reload(monkeypatch, None)


def test_an_empty_variable_falls_back_rather_than_naming_a_blank_vault(monkeypatch):
    creds = _reload(monkeypatch, "   ")
    assert creds.OP_VAULT == "Private"
    _reload(monkeypatch, None)


def test_ansible_reads_the_same_variable():
    root = Path(__file__).resolve().parent.parent.parent
    data = yaml.safe_load((root / "compose" / "group_vars" / "all.yml").read_text())
    value = str(data["op_vault"])
    assert "COVE_OP_VAULT" in value, value
    assert "Private" in value, "the default must still be Private"
