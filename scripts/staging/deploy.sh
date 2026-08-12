#!/usr/bin/env bash
# deploy.sh — deploy current branch to staging (local Cove stack).
#
# Accepts branch name as $1. Builds the wheel from the current branch,
# installs it, re-renders nginx config via `cove up`, starts any new
# compose profiles, and prints the staging URL to stdout.
#
# For Cove, "staging" means the local Docker stack running with the
# branch's changes applied. There is no separate staging server —
# the local stack IS the staging target.

set -euo pipefail

BRANCH="${1:-}"
if [[ -z "$BRANCH" ]]; then
    echo "deploy.sh: branch name required as \$1" >&2
    exit 1
fi

REPO_ROOT="$(git rev-parse --show-toplevel)"
CLI_DIR="$REPO_ROOT/cli"

echo "Building wheel from branch: $BRANCH" >&2

# Build the wheel from the current branch
WHEEL_DIR=$(mktemp -d)
if ! uv build --directory "$CLI_DIR" --wheel --out-dir "$WHEEL_DIR" 2>&1 >&2; then
    echo "deploy.sh: wheel build failed" >&2
    rm -rf "$WHEEL_DIR"
    exit 1
fi

WHEEL=$(ls "$WHEEL_DIR"/cove_cli-*.whl | head -1)
if [[ -z "$WHEEL" ]]; then
    echo "deploy.sh: no wheel produced" >&2
    rm -rf "$WHEEL_DIR"
    exit 1
fi

echo "Installing wheel: $(basename "$WHEEL")" >&2

# Install into a staging venv
STAGING_VENV="$REPO_ROOT/.staging-venv"
if [[ -d "$STAGING_VENV" ]]; then
    rm -rf "$STAGING_VENV"
fi
python3 -m venv "$STAGING_VENV"
"$STAGING_VENV/bin/pip" install --quiet "$WHEEL"
"$STAGING_VENV/bin/pip" install --quiet click cryptography jinja2 pyyaml requests

rm -rf "$WHEEL_DIR"

# Add staging venv to PATH for cove commands
export PATH="$STAGING_VENV/bin:$PATH"

echo "Running cove up to re-render nginx config and restart containers..." >&2

# Run cove up with --no-provision (skip Forgejo/Vault provisioning)
# and --skip-trust-store (staging doesn't need system trust store)
# cove up may return non-zero if Vault is sealed or optional services
# aren't running — that's OK for staging, we just need the containers up.
cove up --no-provision 2>&1 >&2 || true

# Verify nginx is actually running
if ! docker ps --filter "name=cove-nginx" --format "{{.Status}}" | grep -q "Up"; then
    echo "deploy.sh: nginx container is not running after cove up" >&2
    exit 1
fi

# Start any new compose profiles defined in the branch
# (e.g., litellm profile for the litellm-hardening branch)
# Start any new compose profiles defined in the branch
# (e.g., litellm profile for the litellm-hardening branch)
if docker compose --project-directory "$REPO_ROOT/compose" config --profiles 2>/dev/null | grep -q "litellm"; then
    echo "Starting litellm profile..." >&2
    docker compose --project-directory "$REPO_ROOT/compose" --profile litellm up -d litellm headroom 2>&1 >&2 || true
    # Wait for litellm to be healthy
    for i in $(seq 1 30); do
        if docker inspect cove-litellm --format '{{.State.Health.Status}}' 2>/dev/null | grep -q "healthy"; then
            break
        fi
        sleep 2
    done
fi

# Start the speedtest profile (internet-link monitor)
if docker compose --project-directory "$REPO_ROOT/compose" config --profiles 2>/dev/null | grep -q "speedtest"; then
    echo "Starting speedtest profile..." >&2
    # The auto-gen APP_KEY flow needs the 1Password biometric prompt, so set
    # an env override if not already present to avoid blocking on it.
    if [ -z "${SPEEDTEST_APP_KEY:-}" ]; then
        export SPEEDTEST_APP_KEY="base64:$(openssl rand -base64 32)"
    fi
    docker compose --project-directory "$REPO_ROOT/compose" --profile speedtest up -d speedtest-tracker 2>&1 >&2 || true
    # Wait for speedtest to be healthy
    for i in $(seq 1 30); do
        if docker inspect cove-speedtest-tracker --format '{{.State.Health.Status}}' 2>/dev/null | grep -q "healthy"; then
            break
        fi
        sleep 2
    done
fi

# Print the staging URL to stdout (consumed by e2e.sh)
echo "https://127.0.0.1:8443"