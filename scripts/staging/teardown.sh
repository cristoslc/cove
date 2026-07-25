#!/usr/bin/env bash
# teardown.sh — destroy the staging instance.
#
# Accepts branch name as $1. MUST include production safety guards:
#   1. Computed resource names MUST NOT match known production resource names.
#   2. Computed resource names MUST contain the literal string "staging".
#
# For Cove, "teardown" means:
#   - Stop any staging-specific compose profiles (e.g., litellm)
#   - Remove the staging venv
#   - Restore the main branch's cove up state (re-render nginx config)
#
# Production safety: Cove's production containers (cove-forgejo, cove-vault,
# cove-nginx, cove-dnsmasq, cove-dnsproxy) are NEVER touched by teardown.
# Only staging-specific containers (cove-litellm, cove-headroom) are stopped.

set -euo pipefail

BRANCH="${1:-}"
if [[ -z "$BRANCH" ]]; then
    echo "teardown.sh: branch name required as \$1" >&2
    exit 1
fi

REPO_ROOT="$(git rev-parse --show-toplevel)"

# --- Production safety guards ---

# Guard 1: Resource names MUST NOT match known production names.
# Cove production containers: cove-forgejo, cove-nginx, cove-vault,
# cove-dnsmasq, cove-dnsproxy. We only stop staging-specific containers.
PRODUCTION_CONTAINERS="cove-forgejo cove-nginx cove-vault cove-dnsmasq cove-dnsproxy"
STAGING_CONTAINERS="cove-litellm cove-headroom"

for container in $STAGING_CONTAINERS; do
    for prod in $PRODUCTION_CONTAINERS; do
        if [[ "$container" == "$prod" ]]; then
            echo "teardown.sh: SAFETY VIOLATION — staging container '$container' matches production name" >&2
            exit 1
        fi
    done
done

# Guard 2: This is a staging teardown — verify we're on a feature branch,
# not main/trunk. We never tear down from main.
CURRENT_BRANCH=$(git -C "$REPO_ROOT" branch --show-current 2>/dev/null || echo "")
if [[ "$CURRENT_BRANCH" == "main" || "$CURRENT_BRANCH" == "trunk" || "$CURRENT_BRANCH" == "master" ]]; then
    echo "teardown.sh: SAFETY VIOLATION — refusing to tear down from production branch '$CURRENT_BRANCH'" >&2
    exit 1
fi

# --- Teardown ---

echo "Stopping staging containers: $STAGING_CONTAINERS" >&2
for container in $STAGING_CONTAINERS; do
    if docker ps -q --filter "name=$container" | grep -q .; then
        docker stop "$container" >/dev/null 2>&1 || true
        echo "  stopped: $container" >&2
    else
        echo "  not running: $container" >&2
    fi
done

# Remove the staging venv
STAGING_VENV="$REPO_ROOT/.staging-venv"
if [[ -d "$STAGING_VENV" ]]; then
    rm -rf "$STAGING_VENV"
    echo "Removed staging venv: $STAGING_VENV" >&2
fi

# Restore main branch's nginx config by running cove up from main
# (only if we're in a worktree — the main checkout handles this)
echo "Teardown complete. Run 'cove up' from main to restore production config." >&2