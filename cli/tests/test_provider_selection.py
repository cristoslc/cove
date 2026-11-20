"""An exported token must not disable the read path that works.

Ruling dec_shji9ces2cnk exported a service account token into the host
environment. The selection logic then chose the SDK provider, which is an
optional extra that no environment on this host installs, so every read failed
even though `op` reads the same references with that token and no prompt.
"""

from __future__ import annotations

import pytest


def test_a_token_without_the_sdk_falls_back_to_the_cli(monkeypatch):
    from cove import secret_providers

    monkeypatch.setenv("OP_SERVICE_ACCOUNT_TOKEN", "ops_example")
    monkeypatch.setattr(secret_providers, "_sdk_available", lambda: False)

    provider = secret_providers.provider_for("op://Private/Cove Admin/password")

    assert provider.name == "1password-cli"


def test_a_token_with_the_sdk_selects_the_unattended_path(monkeypatch):
    from cove import secret_providers

    monkeypatch.setenv("OP_SERVICE_ACCOUNT_TOKEN", "ops_example")
    monkeypatch.setattr(secret_providers, "_sdk_available", lambda: True)

    provider = secret_providers.provider_for("op://Private/Cove Admin/password")

    assert provider.name == "1password-sdk"


def test_no_token_selects_the_cli(monkeypatch):
    from cove import secret_providers

    monkeypatch.delenv("OP_SERVICE_ACCOUNT_TOKEN", raising=False)
    monkeypatch.setattr(secret_providers, "_sdk_available", lambda: True)

    assert secret_providers.provider_for("op://Private/x/y").name == "1password-cli"


def test_an_unknown_scheme_is_refused_rather_than_fallen_back(monkeypatch):
    from cove import secret_providers

    monkeypatch.setattr(secret_providers, "_sdk_available", lambda: True)
    with pytest.raises(Exception):
        secret_providers.provider_for("vault://secret/data/x")
