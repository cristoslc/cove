"""Shared constants for cove CLI modules.

Kept side-effect-free so importing these values never triggers warning
suppression or logging reconfiguration in the importing module.
"""

import os

NGINX_HTTPS_PORT = 443
NGINX_HTTP_PORT = 8080
VAULT_CONTAINER_NAME = "cove-vault"
VAULT_KEYSTORE_PREFIX_DEFAULT = "cove/vault"


def vault_keystore_prefix() -> str:
    """OS-keystore namespace for the secrets server's unseal keys + root token.

    Defaults to ``cove/vault`` so existing installs keep reading the entries
    they have. ``COVE_VAULT_KEYSTORE_PREFIX`` overrides it for rehearsal and
    test runs against a throwaway instance, so a scratch OpenBao can never
    read or overwrite the live unseal material.
    """
    return os.environ.get("COVE_VAULT_KEYSTORE_PREFIX") or VAULT_KEYSTORE_PREFIX_DEFAULT
