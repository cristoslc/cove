#!/usr/bin/env bash
# e2e.sh — run E2E tests against the staging instance.
#
# Accepts a staging URL or identifier as $1. Exits 0 on pass, non-zero on failure.
#
# For Cove, the staging URL is https://127.0.0.1:8443 (the local nginx ingress).
# This script runs the project's tier 2 test command (pytest -m e2e) against
# the deployed staging stack.

set -euo pipefail

STAGING_URL="${1:-https://127.0.0.1:8443}"
REPO_ROOT="$(git rev-parse --show-toplevel)"
CLI_DIR="$REPO_ROOT/cli"

echo "Running E2E tests against: $STAGING_URL" >&2

# Run the tier 2 test command (staging E2E tests marked with @pytest.mark.staging)
# These tests hit the live nginx ingress at 127.0.0.1:8443
cd "$CLI_DIR"
if uv run --directory "$CLI_DIR" pytest -x -q -m staging 2>&1; then
    echo "E2E tests passed" >&2
    exit 0
else
    echo "E2E tests failed" >&2
    exit 1
fi