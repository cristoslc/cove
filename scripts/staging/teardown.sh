#!/usr/bin/env bash
# teardown.sh — destroy the staging instance(s).
#
# Accepts branch name as $1. MUST include production safety guards:
#   1. Computed resource names MUST NOT match known production resource names.
#   2. Computed resource names MUST contain the literal string "staging".
#
# Two staging modes are torn down here:
#
#   A. ISOLATED mode (deploy-isolated.sh): the parallel compose project
#      `cove-staging` — `compose down -v` for that project plus removal of its
#      staging data root (~/Documents/cove-data-staging by default).
#   B. LEGACY in-live mode (deploy.sh): stop the staging-only profile
#      containers (cove-litellm, cove-headroom) and remove the staging venv.
#
# Production safety: the live project's containers (cove-forgejo, cove-vault,
# cove-nginx, cove-dnsmasq, cove-dnsproxy, cove-ade-server, ...) are NEVER
# touched. Guard 3 refuses any compose invocation whose project name is not
# staging-suffixed, and guard 4 refuses to delete any data root that is not.

set -euo pipefail

BRANCH="${1:-}"
if [[ -z "$BRANCH" ]]; then
    echo "teardown.sh: branch name required as \$1" >&2
    exit 1
fi

REPO_ROOT="$(git rev-parse --show-toplevel)"
COMPOSE_DIR="$REPO_ROOT/compose"
STAGING_PROJECT="cove-staging"
STAGING_DATA_ROOT="${COVE_STAGING_DATA_ROOT:-$HOME/Documents/cove-data-staging}"
LIVE_DATA_ROOT="${COVE_LIVE_DATA_ROOT:-$HOME/Documents/cove-data}"

# --- Production safety guards -------------------------------------------------

# Guard 1: Resource names MUST NOT match known production names. Since the
# isolated staging mode, cove-litellm/cove-headroom ARE live-stack (production)
# containers whenever the operator runs those profiles — teardown never stops
# anything whose name matches production. Stopping live optional profiles is
# the operator's explicit `cove litellm down`, not a staging teardown.
PRODUCTION_CONTAINERS="cove-forgejo cove-nginx cove-vault cove-dnsmasq cove-dnsproxy cove-ade-server cove-litellm cove-litellm-db cove-headroom cove-speedtest-tracker cove-forgejo-runner cove-tunnel"
STAGING_CONTAINERS=""

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

# Guard 3: the isolated compose project name must be staging-suffixed so a
# compose `down` can never target the live project (`cove`).
if [[ "$STAGING_PROJECT" != *"staging"* || "$STAGING_PROJECT" == "cove" ]]; then
    echo "teardown.sh: SAFETY VIOLATION — compose project '$STAGING_PROJECT' is not staging-isolated" >&2
    exit 1
fi

# Guard 4: the staging data root must contain "staging" AND must not equal the
# live data root. (The check is equality plus the "staging" substring marker,
# not an ancestor walk.)
if [[ "$STAGING_DATA_ROOT" != *"staging"* || "$STAGING_DATA_ROOT" == "$LIVE_DATA_ROOT" ]]; then
    echo "teardown.sh: SAFETY VIOLATION — staging data root '$STAGING_DATA_ROOT' is not isolated from live root '$LIVE_DATA_ROOT'" >&2
    exit 1
fi

# --- A. Isolated project teardown (cove-staging) ------------------------------

if docker info >/dev/null 2>&1; then
    ISOLATED_IDS=$(docker ps -aq --filter "label=com.docker.compose.project=$STAGING_PROJECT" 2>/dev/null || true)
    if [[ -n "$ISOLATED_IDS" ]]; then
        echo "Tearing down isolated staging project: $STAGING_PROJECT" >&2
        DOWN_ARGS=(-p "$STAGING_PROJECT"
            -f "$COMPOSE_DIR/docker-compose.yml"
            -f "$COMPOSE_DIR/docker-compose.staging.yml"
            # Enable every profile deploy-isolated.sh may have started; a
            # profile-gated service whose profile is NOT enabled here is not
            # part of the project for this down (and --remove-orphans does
            # not catch it), leaving an orphan container behind (observed:
            # cove-staging-toolhive survived a --profile ade teardown).
            --profile ade
            --profile mcp
            down -v --remove-orphans)
        DOWN_CMD=(docker compose)
        if [[ -f "$STAGING_DATA_ROOT/staging.env" ]]; then
            DOWN_CMD+=(--env-file "$STAGING_DATA_ROOT/staging.env")
        fi
        DOWN_CMD+=("${DOWN_ARGS[@]}")
        if ! "${DOWN_CMD[@]}" 2>&1 >&2; then
            echo "teardown.sh: isolated compose down failed" >&2
            exit 1
        fi
        echo "  removed project: $STAGING_PROJECT (containers, network, volumes)" >&2
    else
        echo "Isolated staging project '$STAGING_PROJECT' not present (nothing to do)" >&2
    fi
else
    echo "Docker daemon not reachable — skipping isolated project teardown" >&2
fi

# Remove the staging data dir created by deploy-isolated.sh. Guard 4 above
# already ensured it is staging-suffixed and not the live root.
if [[ -d "$STAGING_DATA_ROOT" ]]; then
    rm -rf "$STAGING_DATA_ROOT"
    echo "Removed staging data root: $STAGING_DATA_ROOT" >&2
fi

# --- B. Legacy in-live staging cleanup (deploy.sh mode) ------------------------

for container in $STAGING_CONTAINERS; do
    if docker ps -q --filter "name=$container" | grep -q .; then
        docker stop "$container" >/dev/null 2>&1 || true
        echo "  stopped: $container" >&2
    else
        echo "  not running: $container" >&2
    fi
done

STAGING_VENV="$REPO_ROOT/.staging-venv"
if [[ -d "$STAGING_VENV" ]]; then
    rm -rf "$STAGING_VENV"
    echo "Removed staging venv: $STAGING_VENV" >&2
fi

echo "Teardown complete." >&2
