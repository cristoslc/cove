"""The official-SDK 1Password path (ruling dec_fgl9wusck656).

The properties that matter: no token means a loud failure naming the variable,
a create when the item is absent, an in-place field update when it exists, and
a value that never has to travel through argv.
"""

from __future__ import annotations

import asyncio

import pytest
from click.testing import CliRunner

from cove import op_sdk


class FakeField:
    def __init__(self, **kwargs):
        self.id = kwargs.get("id")
        self.title = kwargs.get("title")
        self.field_type = kwargs.get("field_type")
        self.value = kwargs.get("value")


class FakeParams:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class FakeItem:
    def __init__(self, id="item-1", title="", fields=None):
        self.id = id
        self.title = title
        self.fields = list(fields or [])


class FakeSdk:
    ItemCreateParams = FakeParams
    ItemField = FakeField

    class ItemFieldType:
        CONCEALED = "concealed"

    class ItemCategory:
        APICREDENTIALS = "api_credentials"


class FakeOverview:
    def __init__(self, id, title):
        self.id = id
        self.title = title


class FakeVault:
    def __init__(self, id, title):
        self.id = id
        self.title = title


class FakeVaults:
    def __init__(self, vaults):
        self._vaults = vaults

    async def list(self):
        return list(self._vaults)


class FakeItems:
    def __init__(self, existing=None):
        self.existing = existing or []
        self.created = []
        self.putted = []

    async def list(self, vault_id):
        return [FakeOverview(i.id, i.title) for i in self.existing]

    async def create(self, params):
        self.created.append(params)
        return FakeItem(id="new-id", title=params.title)

    async def get(self, vault_id, item_id):
        return self.existing[0]

    async def put(self, item):
        self.putted.append(item)


class FakeSecrets:
    async def resolve(self, ref):
        return f"value-for-{ref}"


class FakeClient:
    def __init__(self, existing=None):
        self.items = FakeItems(existing)
        self.secrets = FakeSecrets()
        self.vaults = FakeVaults([FakeVault("vault-1", "Private")])


def _patch_client(monkeypatch, client):
    async def factory():
        return client

    monkeypatch.setattr(op_sdk, "_client", factory)
    monkeypatch.setattr(op_sdk, "_sdk", lambda: FakeSdk)


def test_missing_token_fails_loud_and_names_the_variable(monkeypatch):
    monkeypatch.delenv("OP_SERVICE_ACCOUNT_TOKEN", raising=False)
    with pytest.raises(Exception) as excinfo:
        op_sdk.service_account_token()
    assert "OP_SERVICE_ACCOUNT_TOKEN" in str(excinfo.value)


def test_resolve_reads_through_the_sdk(monkeypatch):
    monkeypatch.setenv("OP_SERVICE_ACCOUNT_TOKEN", "fake-token")
    _patch_client(monkeypatch, FakeClient())
    assert op_sdk.resolve("op://Private/Thing/password") == "value-for-op://Private/Thing/password"


def test_create_when_the_title_is_absent(monkeypatch):
    monkeypatch.setenv("OP_SERVICE_ACCOUNT_TOKEN", "fake-token")
    client = FakeClient()
    _patch_client(monkeypatch, client)
    action, item_id = op_sdk.upsert_item(
        vault="Private", title="Renovate Bot (git.cove)", field_id="token", value="sekrit"
    )
    assert action == "created" and item_id == "new-id"
    params = client.items.created[0]
    assert params.title == "Renovate Bot (git.cove)"
    assert params.category == "api_credentials"
    assert params.fields[0].id == "token"
    assert params.fields[0].value == "sekrit"


def test_update_when_the_title_exists(monkeypatch):
    monkeypatch.setenv("OP_SERVICE_ACCOUNT_TOKEN", "fake-token")
    existing = FakeItem(id="old-id", title="Thing", fields=[FakeField(id="token", value="old")])
    client = FakeClient(existing=[existing])
    _patch_client(monkeypatch, client)
    action, item_id = op_sdk.upsert_item(vault="Private", title="Thing", field_id="token", value="new")
    assert action == "updated" and item_id == "old-id"
    assert existing.fields[0].value == "new"
    assert client.items.created == []


def test_field_is_appended_when_absent_on_an_existing_item(monkeypatch):
    monkeypatch.setenv("OP_SERVICE_ACCOUNT_TOKEN", "fake-token")
    existing = FakeItem(id="old-id", title="Thing", fields=[])
    client = FakeClient(existing=[existing])
    _patch_client(monkeypatch, client)
    op_sdk.upsert_item(vault="Private", title="Thing", field_id="token", value="new")
    assert existing.fields[-1].id == "token" and existing.fields[-1].value == "new"


def test_unknown_vault_is_refused(monkeypatch):
    monkeypatch.setenv("OP_SERVICE_ACCOUNT_TOKEN", "fake-token")
    _patch_client(monkeypatch, FakeClient())
    with pytest.raises(Exception) as excinfo:
        op_sdk.upsert_item(vault="Nope", title="X", field_id="token", value="v")
    assert "vault" in str(excinfo.value).lower()


def test_op_read_prefers_the_sdk_when_a_token_is_set(monkeypatch):
    from cove import secret_providers, vault_cache

    # Selection needs the package as well as the token, so the test declares
    # the package rather than inheriting whatever the host happens to have
    # installed. Without this it passes on a machine with the optional extra
    # and fails on a clean one, which is the wrong way round for a gate.
    monkeypatch.setattr(secret_providers, "_sdk_available", lambda: True)
    monkeypatch.setenv("OP_SERVICE_ACCOUNT_TOKEN", "fake-token")
    monkeypatch.setattr(vault_cache, "_op_read_cli", lambda ref: "cli-value", raising=False)
    monkeypatch.setattr(op_sdk, "resolve", lambda ref: "sdk-value")
    assert vault_cache._op_read("op://Private/Thing/password") == "sdk-value"


def test_creds_item_put_reads_the_value_from_a_file(monkeypatch, tmp_path):
    from cove import creds

    secret_file = tmp_path / "token"
    secret_file.write_text("sekrit\n")
    calls = {}

    def fake_upsert(**kwargs):
        calls.update(kwargs)
        return "created", "item-9"

    monkeypatch.setattr(op_sdk, "upsert_item", fake_upsert)
    outcome = CliRunner().invoke(
        creds.creds,
        ["item-put", "--vault", "Private", "--title", "Thing", "--field", "token",
         "--value-file", str(secret_file)],
    )
    assert outcome.exit_code == 0, outcome.output
    assert calls["value"] == "sekrit"
    assert "sekrit" not in outcome.output, "the value must never be printed"
    assert "created" in outcome.output and "item-9" in outcome.output


def test_creds_item_put_refuses_an_empty_file(monkeypatch, tmp_path):
    from cove import creds

    blank = tmp_path / "blank"
    blank.write_text("\n")
    monkeypatch.setattr(
        op_sdk, "upsert_item", lambda **kwargs: pytest.fail("must not be called")
    )
    outcome = CliRunner().invoke(
        creds.creds,
        ["item-put", "--vault", "Private", "--title", "Thing", "--field", "token",
         "--value-file", str(blank)],
    )
    assert outcome.exit_code != 0
    assert "empty" in outcome.output
