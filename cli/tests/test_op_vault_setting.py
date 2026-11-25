"""One setting names the 1Password vault for every reference.

Service accounts cannot read Private, so the vault name is install state. The
CLI and the Ansible vars must read the same variable, or the references and the
provisioning plays would disagree after a vault move.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
import yaml

# A recorded vault name lives under HOME, so every test in this module runs in
# the sandbox home rather than reading (or writing) the developer's own file.
pytestmark = pytest.mark.usefixtures("cove_home")


def _reload(monkeypatch, value: str | None):
    from cove import creds, opvault

    if value is None:
        monkeypatch.delenv("COVE_OP_VAULT", raising=False)
    else:
        monkeypatch.setenv("COVE_OP_VAULT", value)
    # opvault resolves the name at import and creds reads that constant, so the
    # setting is reloaded first and then the module that consumes it.
    importlib.reload(opvault)
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


def test_a_recorded_vault_serves_runs_that_have_no_shell(monkeypatch, cove_home):
    """launchd and bb start without the export, so the name must be on disk."""
    from cove import opvault

    monkeypatch.setenv("COVE_OP_VAULT", "Cove Ops")
    written = opvault.record_install_vault()
    assert written == cove_home / ".config" / "cove" / "op-vault"
    assert written.read_text(encoding="utf-8").strip() == "Cove Ops"

    creds = _reload(monkeypatch, None)
    assert creds.OP_VAULT == "Cove Ops"
    assert creds.OP_REFS["cove_admin_password"] == "op://Cove Ops/Cove Admin/password"


def test_the_variable_wins_over_the_recorded_vault(monkeypatch, cove_home):
    from cove import opvault

    monkeypatch.setenv("COVE_OP_VAULT", "Cove Ops")
    opvault.record_install_vault()
    monkeypatch.setenv("COVE_OP_VAULT", "Scratch")
    assert opvault.vault_name() == "Scratch"


def test_a_run_without_the_variable_leaves_the_record_alone(monkeypatch, cove_home):
    from cove import opvault

    monkeypatch.setenv("COVE_OP_VAULT", "Cove Ops")
    path = opvault.record_install_vault()
    monkeypatch.delenv("COVE_OP_VAULT", raising=False)
    assert opvault.record_install_vault() is None
    assert path.read_text(encoding="utf-8").strip() == "Cove Ops"


def test_state_reports_the_vault_the_cli_reads(monkeypatch):
    from cove import state

    monkeypatch.setenv("COVE_OP_VAULT", "Cove Ops")
    assert state._detect_op_vault() == "Cove Ops"


def test_ansible_reads_the_same_variable():
    root = Path(__file__).resolve().parent.parent.parent
    data = yaml.safe_load((root / "compose" / "group_vars" / "all.yml").read_text())
    value = str(data["op_vault"])
    assert "COVE_OP_VAULT" in value, value
    assert "Private" in value, "the default must still be Private"

def test_every_module_names_the_same_vault(monkeypatch):
    """The per-service modules build their own refs, so they must agree.

    A vault move that only reached the batch-pulled references would leave the
    Bifrost, llmproxy, Speedtest and tunnel refs pointing at Private, and each
    would fail separately at the moment it was used.
    """
    import importlib

    from cove import opvault

    monkeypatch.setenv("COVE_OP_VAULT", "Cove Ops")
    importlib.reload(opvault)
    try:
        assert opvault.OP_VAULT == "Cove Ops"
        for name in ("bifrost", "llmproxy", "speedtest", "tunnel", "creds"):
            module = importlib.reload(importlib.import_module(f"cove.{name}"))
            constant = {
                "bifrost": "BIFROST_OP_VAULT",
                "llmproxy": "LLMPROXY_OP_VAULT",
                "speedtest": "SPEEDTEST_OP_VAULT",
                "tunnel": "TUNNEL_OP_VAULT",
                "creds": "OP_VAULT",
            }[name]
            assert getattr(module, constant) == "Cove Ops", f"{name} disagrees"
    finally:
        monkeypatch.delenv("COVE_OP_VAULT", raising=False)
        importlib.reload(opvault)
        for name in ("bifrost", "llmproxy", "speedtest", "tunnel", "creds"):
            importlib.reload(importlib.import_module(f"cove.{name}"))
