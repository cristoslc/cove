#!/usr/bin/env bash
# SSH Key Vault Cache Script
#
# Cache SSH private keys from 1Password into the cove Vault
# to enable passwordless SSH access without biometric prompts.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "=== SSH Key Vault Cache Script ==="
echo ""

if ! command -v op &> /dev/null; then
    echo "ERROR: 1Password CLI (op) not found."
    exit 1
fi

if ! op account list &> /dev/null; then
    echo "ERROR: 1Password CLI not signed in. Run 'op signin' first."
    exit 1
fi

cd "${REPO_ROOT}/cli"

echo ""
echo "Checking cove Vault status..."
if ! curl -sf http://127.0.0.1:8200/v1/sys/health > /dev/null 2>&1; then
    echo "ERROR: Vault is not running or not healthy."
    echo ""
    echo "To start:"
    echo "  cd ${REPO_ROOT}/compose"
    echo "  docker compose up -d vault"
    echo ""
    echo "Then bootstrap:"
    echo "  ansible-playbook -i inventory.yml bootstrap_vault.yml"
    exit 1
fi

echo "Ensuring Vault is unsealed..."
VAULT_SEALED=$(curl -sf http://127.0.0.1:8200/v1/sys/health | python3 -c "import sys,json; print(json.load(sys.stdin).get('sealed',True))" 2>/dev/null || echo "true")
if [ "$VAULT_SEALED" = "True" ]; then
    echo "Vault is sealed. Attempting unseal..."
    ansible-playbook -i "${REPO_ROOT}/compose/inventory.yml" \
        "${REPO_ROOT}/compose/bootstrap_vault.yml" || {
            echo "ERROR: Vault unseal failed. Cannot cache keys."
            exit 1
        }
fi

echo ""
echo "Vault is ready."
echo ""

echo "=== Caching SSH Keys ==="
echo ""
echo "You will be prompted for 1Password biometric authentication."

echo ""
echo "Caching: Thor Docker VM SSH key (CLC-MBP202212_rsa)..."
uv run cove creds vault-put "op://Private/CLC-MBP202212_rsa/private key" || {
    echo "WARNING: Failed to cache CLC-MBP202212_rsa key"
}

echo ""
echo "Verifying cached credentials..."
if uv run cove creds vault-get "op://Private/CLC-MBP202212_rsa/private key" > /dev/null 2>&1; then
    echo "✓ CLC-MBP202212_rsa: CACHED"
else
    echo "✗ CLC-MBP202212_rsa: NOT FOUND"
fi

echo ""
echo "=== SSH Key Cache Complete ==="
echo ""
echo "You can now run SSH commands without biometric prompts:"
echo "  ssh cristos@192.168.0.23"
echo ""
echo "Re-run this script anytime to refresh the cache."
