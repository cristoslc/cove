#!/usr/bin/env bash
# e2e.sh — run E2E tests against the staging instance.
#
# Accepts a staging URL or identifier as $1. Exits 0 on pass, non-zero on failure.
#
# Default target is the ISOLATED staging stack (deploy-isolated.sh): the
# parallel cove-staging compose project on 127.0.0.1:9443. The legacy
# in-live target (https://127.0.0.1:8443) can still be selected by passing
# it as $1 or BB_STAGING_URL.
# This script runs the project's tier 2 test command (pytest -m staging) against
# the deployed staging stack.

set -euo pipefail

STAGING_URL="${1:-${BB_STAGING_URL:-https://127.0.0.1:9443}}"
export BB_STAGING_URL="$STAGING_URL"
REPO_ROOT="$(git rev-parse --show-toplevel)"
CLI_DIR="$REPO_ROOT/cli"

# Scope: the ISOLATED staging stack (deploy-isolated.sh, port 9443) serves the
# ADE staging surface plus the toolhive staging surface (when the branch
# declares the mcp profile), so only the modules written for it run. The
# legacy in-live staging (deploy.sh, port 8443) serves the FULL staging tier
# sweep (including the dual-marked live-stack tests in test_e2e_dns.py).
TARGET=""
case "$STAGING_URL" in
    *:9443)
        TARGET="tests/test_e2e_ade_staging.py tests/test_e2e_toolhive_staging.py"
        ;;
esac

echo "Running E2E tests against: $STAGING_URL" >&2

# Run the tier 2 test command (staging E2E tests marked with @pytest.mark.staging)
cd "$CLI_DIR"
if uv run --directory "$CLI_DIR" pytest -x -q -m staging $TARGET 2>&1; then
    echo "E2E tests passed" >&2
    exit 0
else
    echo "E2E tests failed" >&2
    exit 1
fi