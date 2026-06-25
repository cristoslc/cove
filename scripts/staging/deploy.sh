#!/usr/bin/env bash
# Deploy branch to a parallel staging stack.
#
# Usage: scripts/staging/deploy.sh <branch-name>
# Stdout: staging URL (e.g. https://127.0.0.1:8444)
# Exit: 0 on success, non-zero on failure.
#
# Creates a staging stack on alternate ports/container names/data-root
# so it runs alongside prod without conflict. No sudo required.
# State is written to $HOME/.cache/cove-staging/state.env for e2e.sh/teardown.sh.
set -euo pipefail

BRANCH_NAME="${1:?Usage: deploy.sh <branch-name>}"
BRANCH_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
CLI_DIR="$BRANCH_DIR/cli"
REAL_HOME="$HOME"
STAGING_DATA="$REAL_HOME/Documents/cove-staging-data"
STAGING_HOME_ROOT="$REAL_HOME/.cache/cove-staging"
STAGING_HOME="$(mktemp -d "$STAGING_HOME_ROOT/home.XXXXXX")"
STATE_FILE="$STAGING_HOME_ROOT/state.env"
LOG_DIR="$(mktemp -d /tmp/cove-staging-logs.XXXXXX)"
COMPOSE_DIR="$STAGING_HOME/.config/cove/compose"
STAGING_HOSTNAME="$(python3 -c 'import platform; print(platform.node().split(".")[0])')"

STAGING_NGINX_HTTPS=8444
STAGING_NGINX_HTTP=8081
STAGING_SSH=2223
STAGING_DNSMASQ=5354
STAGING_URL="https://127.0.0.1:$STAGING_NGINX_HTTPS"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
log()  { echo -e "${GREEN}[$(date +%H:%M:%S)]${NC} $*" | tee -a "$LOG_DIR/deploy.log" >&2; }
warn() { echo -e "${YELLOW}[$(date +%H:%M:%S)] WARN:${NC} $*" | tee -a "$LOG_DIR/deploy.log" >&2; }
fail() { echo -e "${RED}[$(date +%H:%M:%S)] FAIL:${NC} $*" | tee -a "$LOG_DIR/deploy.log" >&2; exit 1; }

# If a prior staging state exists, tear it down first.
if [[ -f "$STATE_FILE" ]]; then
    warn "Prior staging state found — tearing down before redeploy."
    "$BRANCH_DIR/scripts/staging/teardown.sh" "$STAGING_URL" 2>/dev/null || true
    rm -rf "$STAGING_HOME_ROOT"
    STAGING_HOME="$(mktemp -d "$STAGING_HOME_ROOT/home.XXXXXX")"
    COMPOSE_DIR="$STAGING_HOME/.config/cove/compose"
fi

log "=== Staging Deploy: branch=$BRANCH_NAME ==="
log "Staging HOME:  $STAGING_HOME"
log "Staging data:  $STAGING_DATA"
log "Staging URL:   $STAGING_URL"

# ── Prerequisites ──────────────────────────────────────────────────────────
[[ -d "$CLI_DIR/cove/resources/compose" ]] || fail "Bundled resources missing"
command -v docker >/dev/null 2>&1 || fail "docker not found"
docker compose version >/dev/null 2>&1 || fail "docker compose v2 not found"
colima status >/dev/null 2>&1 || fail "Colima not running"
ansible --version >/dev/null 2>&1 || fail "ansible not found"
for port in $STAGING_NGINX_HTTPS $STAGING_NGINX_HTTP $STAGING_SSH $STAGING_DNSMASQ; do
    lsof -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1 && fail "Port $port in use"
done
log "Prerequisites OK."

# ── Build + install wheel ───────────────────────────────────────────────────
UV_VENV="$(mktemp -d /tmp/cove-staging-venv.XXXXXX)"
python3 -m venv "$UV_VENV"
"$UV_VENV/bin/pip" install --quiet "$CLI_DIR" 2>&1 | tee -a "$LOG_DIR/wheel-install.log"
COVE_BIN="$UV_VENV/bin/cove"
[[ -x "$COVE_BIN" ]] || fail "cove binary not found after install"
COVE_VERSION="$("$COVE_BIN" version 2>&1 | awk '{print $2}')"
log "Installed cove $COVE_VERSION"

# ── cove init ───────────────────────────────────────────────────────────────
export HOME="$STAGING_HOME"
"$COVE_BIN" init 2>&1 | tee -a "$LOG_DIR/cove-init.log"
[[ -f "$COMPOSE_DIR/inventory.yml" ]] || fail "cove init failed"
[[ -f "$COMPOSE_DIR/.version" ]] || fail "cove init missing .version"
log "cove init extracted to $COMPOSE_DIR"

# ── Staging env setup ───────────────────────────────────────────────────────
export COVE_ADMIN_USERNAME="staging-test"
export COVE_ADMIN_EMAIL="staging@test.local"
export COVE_OP_VAULT="Private"
export COVE_TS_DNS_NAME="localhost"
export COVE_COMPOSE_DIR="$COMPOSE_DIR"
export COMPOSE_PROJECT_NAME="cove-staging"

mkdir -p "$STAGING_DATA/certs"
ln -sf "$REAL_HOME/.docker" "$STAGING_HOME/.docker"
ln -sf "$REAL_HOME/.colima" "$STAGING_HOME/.colima"

# ── host_vars overlay ───────────────────────────────────────────────────────
HOST_VARS_DIR="$STAGING_HOME/.config/cove/state/hosts"
mkdir -p "$HOST_VARS_DIR"
cat > "$HOST_VARS_DIR/$STAGING_HOSTNAME.yml" <<EOF
admin_username: staging-test
admin_email: staging@test.local
op_vault: Private
ts_dns_name: localhost
cove_data_root: $STAGING_DATA
forgejo_container_name: cove-staging-forgejo
forgejo_ssh_port: $STAGING_SSH
vault_container_name: cove-staging-vault
nginx_container_name: cove-staging-nginx
nginx_conf_dir: $COMPOSE_DIR/nginx
nginx_http_port: $STAGING_NGINX_HTTP
nginx_https_port: $STAGING_NGINX_HTTPS
dnsmasq_container_name: cove-staging-dnsmasq
dnsmasq_conf_dir: $COMPOSE_DIR/dnsmasq
dnsmasq_port: $STAGING_DNSMASQ
dnsproxy_container_name: cove-staging-dnsproxy
cove_skip_tailscale_serve: true
compose_project_name: cove-staging
EOF

# ── Pre-create data dirs + cert symlinks ───────────────────────────────────
mkdir -p "$STAGING_DATA/certs"
for d in forgejo/gitea forgejo/git forgejo/ssh vault/data vault/logs \
         pages/sites nginx nginx/user.d nginx/config/dns dnsmasq; do
    mkdir -p "$STAGING_DATA/$d"
done
ln -sf cove.local.pem "$STAGING_DATA/certs/fullchain.pem"
ln -sf cove.local-key.pem "$STAGING_DATA/certs/privkey.pem"

# ── cove up ────────────────────────────────────────────────────────────────
set +e
export PATH="$UV_VENV/bin:$PATH"
"$COVE_BIN" up --no-sudo --no-provision 2>&1 | tee -a "$LOG_DIR/cove-up.log"
UP_RC=${PIPESTATUS[0]}
set -e
[[ "$UP_RC" -eq 0 ]] || { cat "$LOG_DIR/cove-up.log" >&2; fail "cove up failed (exit $UP_RC)"; }
log "cove up succeeded ✓"

# ── Write state file for e2e.sh/teardown.sh ─────────────────────────────────
cat > "$STATE_FILE" <<EOF
STAGING_URL="$STAGING_URL"
STAGING_HOME="$STAGING_HOME"
STAGING_DATA="$STAGING_DATA"
COMPOSE_DIR="$COMPOSE_DIR"
COVE_BIN="$COVE_BIN"
UV_VENV="$UV_VENV"
LOG_DIR="$LOG_DIR"
STAGING_HOSTNAME="$STAGING_HOSTNAME"
STAGING_NGINX_HTTPS=$STAGING_NGINX_HTTPS
STAGING_NGINX_HTTP=$STAGING_NGINX_HTTP
STAGING_SSH=$STAGING_SSH
STAGING_DNSMASQ=$STAGING_DNSMASQ
COVE_VERSION="$COVE_VERSION"
REAL_HOME="$REAL_HOME"
EOF
log "State written to $STATE_FILE"

# Output staging URL on stdout (sashay protocol reads this).
echo "$STAGING_URL"