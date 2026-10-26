"""Tests for `cove vault` — the standalone unseal verb.

`cove vault unseal` wraps `cove.vault_unseal.ensure_unsealed`, letting an
operator unseal Vault after a reboot without re-running `cove up` (operator
decision 2026-10-22; see docs/musings/cove-serve-autostart.md). Unlike the
autostart path it fails loud.
"""

from unittest.mock import patch

from click import Group
from click.testing import CliRunner


def test_vault_group_registered():
    from cove.cli import app

    assert "vault" in app.commands, "vault group must be registered in cli.py"
    vault_cmd = app.commands["vault"]
    assert isinstance(vault_cmd, Group)
    assert "unseal" in vault_cmd.commands


def test_unseal_invokes_ensure_unsealed():
    from cove.vault import vault

    calls: list = []
    with patch("cove.vault.ensure_unsealed", side_effect=lambda: calls.append(True)):
        result = CliRunner().invoke(vault, ["unseal"])
    assert result.exit_code == 0, result.output
    assert calls == [True], "unseal must delegate to ensure_unsealed"
    assert "Vault unsealed" in result.output


def test_unseal_failure_is_fail_loud():
    from cove.vault import vault

    with patch(
        "cove.vault.ensure_unsealed",
        side_effect=RuntimeError("Keystore read failed for cove/vault/unseal-1"),
    ):
        result = CliRunner().invoke(vault, ["unseal"])
    assert result.exit_code != 0
    assert "Could not unseal Vault" in result.output
    assert "cove vault unseal" in result.output, (
        "the failure must point at the standalone verb's usage"
    )


def test_unseal_or_warn_true_on_success():
    from cove.vault import unseal_or_warn

    with patch("cove.vault.ensure_unsealed", side_effect=lambda: {"sealed": False}):
        assert unseal_or_warn(context="Vault") is True


def test_unseal_or_warn_false_and_warns_on_failure(capsys):
    from cove.vault import unseal_or_warn

    with patch(
        "cove.vault.ensure_unsealed",
        side_effect=RuntimeError("Keystore read failed for cove/vault/unseal-1"),
    ):
        assert unseal_or_warn(context="Vault") is False
    err = capsys.readouterr().err
    assert "could not be unsealed automatically" in err
    assert "cove vault unseal" in err
