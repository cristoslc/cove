#!/usr/bin/env bash
# Tear down staging stack + clean up all staging artifacts.
#
# Usage: scripts/staging/teardown.sh <staging-url>
# Exit: 0 on success, non-zero on failure.
set -euo pipefail

STAGING_URL="${1:-}"
STATE_FILE="$HOME/.cache/cove-staging/state.env"
LOG_DIR="$(mktemp -d /tmp/cove-staging-logs.XXXXXX)"

RED='\033[0;31m'; GREEN='\033[0;32m'; NC='\033[0m'
log() { echo -e "${GREEN}[$(date +%H:%M:%S)]${NC} $*" | tee -a "$LOG_DIR/teardown.log"; }
fail() { echo -e "${RED}[$(date +%H:%M:%S)] FAIL:${NC} $*" | tee -a "$LOG_DIR/teardown.log" >&2; exit 1; }

if [[ ! -f "$STATE_FILE" ]]; then
    log "No staging state file — nothing to tear down."
    exit 0
fi
source "$STATE_FILE"

log "=== Staging Teardown ==="

# ── cove down (graceful) ────────────────────────────────────────────────────
if [[ -n "${COVE_BIN:-}" ]] && [[ -x "$COVE_BIN" ]]; then
    log "Running cove down..."
    COMPOSE_PROJECT_NAME=cove-staging "$COVE_BIN" down 2>&1 | tee -a "$LOG_DIR/cove-down.log" || true
fi

# ── Force-down any remaining containers ─────────────────────────────────────
if docker ps --filter "name=cove-staging" --format '{{.Names}}' | grep -q cove-staging; then
    log "Force-removing staging containers..."
    docker compose --project-name cove-staging --project-directory "$COMPOSE_DIR" down \
        --remove-orphans 2>&1 | tee -a "$LOG_DIR/docker-down.log" || true
fi

# ── Stop staging-only Colima VMs (NEVER touch prod VM) ──────────────────────
# Only stop if staging spawned its own VM (.colima is a real dir, NOT a symlink
# to prod's Colima). If .colima is a symlink, staging reused prod's VM.
if [[ -n "${STAGING_HOME:-}" ]]; then
    if [[ -L "$STAGING_HOME/.colima" ]]; then
        log "Staging reused prod Colima VM via symlink — nothing to stop."
    elif [[ -d "$STAGING_HOME/.colima" ]]; then
        log "Stopping staging-only Colima VM..."
        LIMA_HOME="$STAGING_HOME/.colima" colima stop -f 2>/dev/null || true
        LIMA_HOME="$STAGING_HOME/.colima" colima delete -f 2>/dev/null || true
    fi
fi

# ── Remove staging artifacts ───────────────────────────────────────────────
log "Removing staging data dir..."
rm -rf "$STAGING_DATA" 2>/dev/null || true

log "Removing staging HOME..."
rm -rf "$STAGING_HOME" 2>/dev/null || true
rm -rf "$HOME/.cache/cove-staging" 2>/dev/null || true

log "Removing staging venv..."
rm -rf "${UV_VENV:-}" 2>/dev/null || true

# ── Verify clean ────────────────────────────────────────────────────────────
sleep 2
REMAINING=$(docker ps -a --filter "name=cove-staging" --format '{{.Names}}' | wc -l | tr -d ' ')
if [[ "$REMAINING" -ne 0 ]]; then
    warn "WARNING: $REMAINING staging containers still present (may be terminating)"
else
    log "No staging containers remaining ✓"
fi

log "Staging teardown complete. Logs: $LOG_DIR"

exit 0