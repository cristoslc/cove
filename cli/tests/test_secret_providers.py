"""The provider seam: one backend today, a protocol that admits another tomorrow."""

from __future__ import annotations

import pytest

from cove import secret_providers


def test_a_service_account_token_selects_the_sdk(monkeypatch):
    # The token is one of two inputs; the package is the other. Declaring the
    # package keeps this test about the rule rather than about the host.
    from cove import secret_providers

    monkeypatch.setattr(secret_providers, "_sdk_available", lambda: True)
    monkeypatch.setenv("OP_SERVICE_ACCOUNT_TOKEN", "fake-token")
    provider = secret_providers.provider_for("op://Private/Thing/password")
    assert provider.name == "1password-sdk"


def test_without_a_token_the_cli_is_the_provider(monkeypatch):
    monkeypatch.delenv("OP_SERVICE_ACCOUNT_TOKEN", raising=False)
    provider = secret_providers.provider_for("op://Private/Thing/password")
    assert provider.name == "1password-cli"


def test_an_unknown_scheme_is_refused_by_name(monkeypatch):
    monkeypatch.delenv("OP_SERVICE_ACCOUNT_TOKEN", raising=False)
    with pytest.raises(Exception) as excinfo:
        secret_providers.provider_for("bw://Private/Thing/password")
    message = str(excinfo.value)
    assert "unsupported secret reference" in message
    assert "op://" in message


def test_the_sdk_provider_refuses_without_a_token(monkeypatch):
    monkeypatch.delenv("OP_SERVICE_ACCOUNT_TOKEN", raising=False)
    with pytest.raises(Exception) as excinfo:
        secret_providers.OnePasswordSdk().validate("op://Private/Thing/password")
    assert "OP_SERVICE_ACCOUNT_TOKEN" in str(excinfo.value)


def test_read_secret_routes_through_the_selected_provider(monkeypatch):
    monkeypatch.setattr(secret_providers, "_sdk_available", lambda: True)
    monkeypatch.setenv("OP_SERVICE_ACCOUNT_TOKEN", "fake-token")
    monkeypatch.setattr(
        secret_providers.OnePasswordSdk, "read", lambda self, ref: f"sdk:{ref}"
    )
    assert secret_providers.read_secret("op://Private/Thing/password") == (
        "sdk:op://Private/Thing/password"
    )


def test_read_secret_uses_the_cli_without_a_token(monkeypatch):
    monkeypatch.delenv("OP_SERVICE_ACCOUNT_TOKEN", raising=False)
    monkeypatch.setattr(
        secret_providers.OnePasswordCli, "read", lambda self, ref: f"cli:{ref}"
    )
    assert secret_providers.read_secret("op://Private/Thing/password") == (
        "cli:op://Private/Thing/password"
    )


def test_the_protocol_is_satisfied_by_both_providers():
    assert isinstance(secret_providers.OnePasswordSdk(), secret_providers.SecretProvider)
    assert isinstance(secret_providers.OnePasswordCli(), secret_providers.SecretProvider)
