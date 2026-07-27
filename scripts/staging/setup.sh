#!/usr/bin/env bash
# setup.sh — credential caching, environment validation, budget gate.
#
# Accepts branch name as $1. Exits 0 on pass, non-zero on failure.
# Produces checklist format with [✓]/[✗] prefixes on stdout.
#
# For Cove (local-first), this validates:
#   - Docker daemon is running (Colima on macOS)
#   - Cove stack is up (nginx ingress reachable)
#   - No external cloud resources to budget (local-only)

set -euo pipefail

BRANCH="${1:-}"
if [[ -z "$BRANCH" ]]; then
    echo "[✗] branch name argument"
    exit 1
fi
echo "[✓] branch name argument: $BRANCH"

# Check Docker daemon
if ! docker info >/dev/null 2>&1; then
    echo "[✗] Docker daemon (start Colima: colima start)"
    exit 1
fi
echo "[✓] Docker daemon running"

# Check Docker context is Colima (macOS)
if [[ "$(uname)" == "Darwin" ]]; then
    CONTEXT=$(docker context show 2>/dev/null || echo "")
    if [[ "$CONTEXT" != "colima" ]]; then
        echo "[✗] Docker context (expected 'colima', got '$CONTEXT')"
        exit 1
    fi
    echo "[✓] Docker context: colima"
fi

# Check Cove nginx ingress is reachable
if ! curl -sf -k -H "Host: hc.cove.local" https://127.0.0.1:8443/ >/dev/null 2>&1 && \
   ! curl -sf -k -H "Host: hc.cove" https://127.0.0.1:8443/ >/dev/null 2>&1; then
    echo "[✗] Cove nginx ingress (run 'cove up' first)"
    exit 1
fi
echo "[✓] Cove nginx ingress reachable"

# No cloud resources to budget — Cove is local-first
echo "[✓] budget check: local-only, no cloud resources"

echo ""
echo "Setup complete. Ready to deploy branch: $BRANCH"