#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "==> Reinstalling cove-cli from source..."
uv tool install --reinstall ./cli
echo "==> Done. Verify with: cove --help"
