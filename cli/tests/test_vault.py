"""Tests for `cove vault` — unseal, converge-up, and status.

`cove vault unseal` wraps `cove.vault_unseal.ensure_unsealed`, letting an
operator unseal Vault after a reboot without re-running `cove up` (operator
decision 2026-10-22; see docs/musings/cove-serve-autostart.md). Unlike the
autostart path it fails loud.

`cove vault up` is the idempotent converge: start the service, wait for the
API, then unseal only when sealed. All Docker/subprocess access is mocked at
the boundary; these tests never touch a live container.
"""

import subprocess
from pathlib import Path
from unittest.mock import patch

from click import Group
from click.testing import CliRunner

COMPOSE_DIR = Path("/nonexistent/cove-test-compose")


def _invoke_up(*, health=None, health_error=None, unseal_error=None):
    """Invoke `cove vault up` with the Docker boundary and Vault API mocked."""
    from cove.vault import vault

    health_patch = (
        patch("cove.vault.vault_health", side_effect=health_error)
        if health_error is not None
        else patch("cove.vault.vault_health", return_value=health)
    )
    with patch("cove.vault.resolve_compose_dir", return_value=COMPOSE_DIR), patch(
        "cove.vault.ensure_compose_source_ready"
    ), patch("cove.vault.subprocess.run") as compose_run, health_patch, patch(
        "cove.vault.ensure_unsealed",
        side_effect=unseal_error,
        return_value={"initialized": True, "sealed": False},
    ) as unseal:
        result = CliRunner().invoke(vault, ["up"])
    return result, compose_run, unseal


def test_vault_group_registered():
    from cove.cli import app

    assert "vault" in app.commands, "vault group must be registered in cli.py"
    vault_cmd = app.commands["vault"]
    assert isinstance(vault_cmd, Group)
    assert {"up", "status", "unseal"} <= set(vault_cmd.commands)


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


# --- `cove vault up` — idempotent converge ---------------------------------


def test_up_sealed_starts_service_and_unseals():
    result, compose_run, unseal = _invoke_up(
        health={"initialized": True, "sealed": True}
    )

    assert result.exit_code == 0, result.output
    assert unseal.call_count == 1, "a sealed Vault must be unsealed exactly once"
    assert "unsealed" in result.output.lower()

    compose_cmd = compose_run.call_args.args[0]
    assert compose_cmd[compose_cmd.index("up"):] == ["up", "-d", "vault"], (
        "`cove vault up` must bring up the vault service first"
    )


def test_up_unsealed_is_idempotent_noop():
    result, compose_run, unseal = _invoke_up(
        health={"initialized": True, "sealed": False}
    )

    assert result.exit_code == 0, result.output
    unseal.assert_not_called()
    assert "already unsealed" in result.output.lower()
    assert compose_run.called, "the service must still be ensured up"


def test_up_unseal_failure_is_loud_and_names_recovery():
    result, _compose_run, unseal = _invoke_up(
        health={"initialized": True, "sealed": True},
        unseal_error=RuntimeError("Keystore read failed for cove/vault/unseal-1"),
    )

    assert unseal.call_count == 1
    assert result.exit_code != 0, "an unseal failure must fail the verb"
    assert "could not be unsealed" in result.output.lower()
    assert "cove vault unseal" in result.output, (
        "the error must name the recovery command"
    )


def test_up_times_out_when_vault_never_answers():
    with patch("cove.vault.VAULT_READY_TIMEOUT_S", 0.0):
        result, _compose_run, _unseal = _invoke_up(
            health_error=RuntimeError("Vault unreachable at https://vault.cove.local/")
        )

    assert result.exit_code != 0
    assert "did not become ready" in result.output.lower()
    assert "docker compose logs vault" in result.output


def test_up_fails_loud_when_service_start_fails():
    from cove.vault import vault

    with patch("cove.vault.resolve_compose_dir", return_value=COMPOSE_DIR), patch(
        "cove.vault.ensure_compose_source_ready"
    ), patch(
        "cove.vault.subprocess.run",
        side_effect=subprocess.CalledProcessError(1, ["docker", "compose"]),
    ), patch("cove.vault.vault_health") as health:
        result = CliRunner().invoke(vault, ["up"])

    assert result.exit_code != 0
    assert "Could not start the Vault service" in result.output
    health.assert_not_called()


def test_up_fails_loud_when_vault_not_initialized():
    result, _compose_run, unseal = _invoke_up(
        health={"initialized": False, "sealed": True}
    )

    assert result.exit_code != 0
    assert "not initialized" in result.output
    unseal.assert_not_called()


# --- `cove vault status` — explicit state -----------------------------------


def test_status_reports_sealed():
    from cove.vault import vault

    with patch(
        "cove.vault.vault_health",
        return_value={"initialized": True, "sealed": True},
    ):
        result = CliRunner().invoke(vault, ["status"])

    assert result.exit_code != 0, "a sealed Vault is not a healthy status"
    assert "initialized, sealed" in result.output
    assert "cove vault up" in result.output


def test_status_reports_unsealed():
    from cove.vault import vault

    with patch(
        "cove.vault.vault_health",
        return_value={"initialized": True, "sealed": False},
    ):
        result = CliRunner().invoke(vault, ["status"])

    assert result.exit_code == 0, result.output
    assert "initialized, unsealed" in result.output


def test_status_reports_not_initialized():
    from cove.vault import vault

    with patch(
        "cove.vault.vault_health",
        return_value={"initialized": False, "sealed": True},
    ):
        result = CliRunner().invoke(vault, ["status"])

    assert result.exit_code != 0
    assert "not initialized" in result.output


def test_status_unreachable_is_loud():
    from cove.vault import vault

    with patch(
        "cove.vault.vault_health",
        side_effect=RuntimeError("Vault unreachable at https://vault.cove.local/"),
    ):
        result = CliRunner().invoke(vault, ["status"])

    assert result.exit_code != 0
    assert "unreachable" in result.output.lower()
    assert "cove vault up" in result.output
