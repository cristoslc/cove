"""Unattended 1Password access through the official SDK.

Operator ruling (`dec_fgl9wusck656`): the CLI never reports a session inside an
agent shell, the installed community MCP would put single-maintainer code in
front of the vault, and Connect needs a plan tier. The official SDK behind a
scoped service-account token is the smallest surface that can read and write
the handful of items Cove needs.

The token comes from ``OP_SERVICE_ACCOUNT_TOKEN``. Absent, every entry point
fails loud naming the variable rather than falling back to the CLI, because a
silent fallback is how an unattended write becomes a hang.
"""

from __future__ import annotations

import asyncio
import os
from importlib.metadata import PackageNotFoundError, version

import click

INTEGRATION_NAME = "cove"


def _sdk():
    try:
        import onepassword  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - depends on the host install
        raise click.ClickException(
            "the 1Password SDK is not installed; install the optional extra "
            "(`uv pip install onepassword-sdk`) before using this path"
        ) from exc
    return onepassword


def service_account_token() -> str:
    token = os.environ.get("OP_SERVICE_ACCOUNT_TOKEN", "").strip()
    if not token:
        raise click.ClickException(
            "OP_SERVICE_ACCOUNT_TOKEN is not set. Cove reads 1Password through a "
            "service account: create one scoped to the vaults it needs, then "
            "export the token before using this path."
        )
    return token


def _integration_version() -> str:
    try:
        return version("cove-cli")
    except PackageNotFoundError:  # pragma: no cover - source checkouts
        return "0.0.0"


async def _client():
    sdk = _sdk()
    return await sdk.Client.authenticate(
        auth=service_account_token(),
        integration_name=INTEGRATION_NAME,
        integration_version=_integration_version(),
    )


async def _vault_id(client, vault: str) -> str:
    vaults = await client.vaults.list()
    for candidate in vaults:
        if candidate.id == vault or candidate.title == vault:
            return candidate.id
    raise click.ClickException(f"no 1Password vault matching {vault!r} is visible to this account")


def resolve(ref: str) -> str:
    """Read one secret reference through the SDK."""

    async def run() -> str:
        client = await _client()
        return await client.secrets.resolve(ref)

    return asyncio.run(run())


def upsert_item(*, vault: str, title: str, field_id: str, value: str) -> tuple[str, str]:
    """Create the item, or update only this field when the title already exists.

    Returns ``(action, item_id)`` where action is ``created`` or ``updated``.
    """

    async def run() -> tuple[str, str]:
        sdk = _sdk()
        client = await _client()
        vault_id = await _vault_id(client, vault)
        overviews = await client.items.list(vault_id)
        existing = next((item for item in overviews if item.title == title), None)
        if existing is None:
            item = await client.items.create(
                sdk.ItemCreateParams(
                    category=sdk.ItemCategory.APICREDENTIALS,
                    vault_id=vault_id,
                    title=title,
                    fields=[
                        sdk.ItemField(
                            id=field_id,
                            title=field_id,
                            field_type=sdk.ItemFieldType.CONCEALED,
                            value=value,
                        )
                    ],
                )
            )
            return "created", item.id

        item = await client.items.get(vault_id, existing.id)
        replaced = False
        for field in item.fields:
            if field.id == field_id or field.title == field_id:
                field.value = value
                replaced = True
                break
        if not replaced:
            item.fields.append(
                sdk.ItemField(
                    id=field_id,
                    title=field_id,
                    field_type=sdk.ItemFieldType.CONCEALED,
                    value=value,
                )
            )
        await client.items.put(item)
        return "updated", existing.id

    return asyncio.run(run())
