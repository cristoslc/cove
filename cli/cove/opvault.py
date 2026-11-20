"""The one 1Password vault every Cove reference names.

Service accounts cannot read `Private`, so the vault name is install state, not
source. It is one setting because a vault move must not mean editing references
in five modules: `COVE_OP_VAULT` names the vault, `cli/cove/creds.py` builds the
batch-pulled references from it, the per-service modules build theirs from the
same constant here, and `compose/group_vars/all.yml` renders `op_vault` from the
same variable, which `cove up` passes through to Ansible.

An empty or whitespace value falls back to `Private` rather than naming a blank
vault, because a blank name produces `<vault>/<item>` style errors that read as
missing items instead of a missing setting.
"""

from __future__ import annotations

import os

DEFAULT_VAULT = "Private"


def vault_name() -> str:
    """Resolve the vault name from the environment, falling back to Private."""
    return os.environ.get("COVE_OP_VAULT", "").strip() or DEFAULT_VAULT


# Resolved once at import, like every other module constant here. A test that
# needs another value reloads the module, which is what the existing vault tests
# already do.
OP_VAULT: str = vault_name()
