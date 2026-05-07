#!/usr/bin/env bash
set -euo pipefail

OLD_DATA="/Users/cristos/Documents/local-pod-data/forgejo"

echo "=== Cleanup Old Forgejo Data ==="
echo ""

echo "[1/1] Removing old data directory..."
read -p "  Delete $OLD_DATA? (y/N) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    sudo rm -rf "$OLD_DATA"
    echo "  Deleted."
else
    echo "  Skipped — kept at $OLD_DATA"
fi

echo ""
echo "=== Cleanup complete ==="
echo "Note: /etc/hosts entry (mbpbk-202602.taila90e7.ts.net) must remain for local FQDN resolution."
