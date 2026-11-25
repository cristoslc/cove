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

A scheduled run has no shell, so an exported variable would not reach it: the
daily `cove update` agent and the merge gate start from launchd and bb, where
`Private` would be read after a move. `cove up` therefore records the exported
name in a one-line install-state file, and resolution reads that file when the
variable is absent. The file holds a vault name, not a secret.
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_VAULT = "Private"


def install_vault_file() -> Path:
    """The install-state file an exported `COVE_OP_VAULT` is recorded in."""
    return Path.home() / ".config" / "cove" / "op-vault"


def vault_name() -> str:
    """Resolve the vault name: environment, then install state, then Private."""
    from_env = os.environ.get("COVE_OP_VAULT", "").strip()
    if from_env:
        return from_env
    try:
        recorded = install_vault_file().read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return DEFAULT_VAULT
    return recorded or DEFAULT_VAULT


def record_install_vault() -> Path | None:
    """Record an exported `COVE_OP_VAULT` so shell-less runs resolve it too.

    Returns the file written, or None when the environment names no vault (a
    run without the variable must not overwrite what an earlier one recorded).
    """
    name = os.environ.get("COVE_OP_VAULT", "").strip()
    if not name:
        return None
    path = install_vault_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(name + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


# Resolved once at import, like every other module constant here. A test that
# needs another value reloads the module, which is what the existing vault tests
# already do.
OP_VAULT: str = vault_name()
