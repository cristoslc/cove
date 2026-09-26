#!/usr/bin/env bash
# deploy-isolated.sh — deploy the current branch to an ISOLATED staging stack.
#
# Unlike deploy.sh (which runs `cove up` and therefore re-renders/restarts the
# LIVE cove containers), this script runs the branch as a PARALLEL Docker
# Compose project (`-p cove-staging`) in the same Colima VM:
#
#   docker compose -p cove-staging \
#     -f compose/docker-compose.yml -f compose/docker-compose.staging.yml \
#     --env-file <staging.env> --project-directory compose \
#     up -d --build
#
# Isolation guarantees (asserted by cli/tests/test_staging_isolation.py):
#   - container names: cove-staging-* (never cove-nginx, cove-forgejo, ...),
#   - host ports: only 127.0.0.1:9443 (nginx); no other host bindings,
#   - data: everything under $COVE_STAGING_DATA_ROOT (default
#     ~/Documents/cove-data-staging); the live root ~/Documents/cove-data is
#     only ever READ (certs/dnsmasq conf are copied out, never mounted/written).
#   - no `cove` CLI invocation, so no 1Password/biometric paths and no live
#     nginx re-render.
#
# Usage: deploy-isolated.sh <branch>
# Prints the staging base URL (https://127.0.0.1:9443) to stdout on success.
# Any critical failure exits non-zero.

set -euo pipefail

BRANCH="${1:-}"
if [[ -z "$BRANCH" ]]; then
    echo "deploy-isolated.sh: branch name required as \$1" >&2
    exit 1
fi

REPO_ROOT="$(git rev-parse --show-toplevel)"
COMPOSE_DIR="$REPO_ROOT/compose"
CLI_DIR="$REPO_ROOT/cli"
STAGING_PROJECT="cove-staging"
STAGING_HTTPS_PORT="${STAGING_NGINX_HTTPS_PORT:-9443}"
STAGING_DATA_ROOT="${COVE_STAGING_DATA_ROOT:-$HOME/Documents/cove-data-staging}"
LIVE_DATA_ROOT="${COVE_LIVE_DATA_ROOT:-$HOME/Documents/cove-data}"
ADE_PORT="${ADE_PORT:-38886}"

# --- Safety guards: the staging root must never be the live root -------------
if [[ "$STAGING_DATA_ROOT" == "$LIVE_DATA_ROOT" ]]; then
    echo "deploy-isolated.sh: SAFETY VIOLATION — staging data root equals live root ($LIVE_DATA_ROOT)" >&2
    exit 1
fi
if [[ "$STAGING_DATA_ROOT" != *"staging"* ]]; then
    echo "deploy-isolated.sh: SAFETY VIOLATION — staging data root '$STAGING_DATA_ROOT' does not contain 'staging'" >&2
    exit 1
fi

if ! docker info >/dev/null 2>&1; then
    echo "deploy-isolated.sh: Docker daemon not reachable (start Colima: colima start)" >&2
    exit 1
fi

echo "Isolated staging deploy — branch: $BRANCH" >&2
echo "  project:      $STAGING_PROJECT" >&2
echo "  data root:    $STAGING_DATA_ROOT" >&2
echo "  nginx:        https://127.0.0.1:$STAGING_HTTPS_PORT (Host: ade.cove)" >&2
echo "  live stack:   untouched (no cove up, no live container restarts)" >&2

# --- Build the branch wheel + venv (same as deploy.sh; venv provides jinja2) -
WHEEL_DIR=$(mktemp -d)
trap 'rm -rf "$WHEEL_DIR"' EXIT
if ! uv build --directory "$CLI_DIR" --wheel --out-dir "$WHEEL_DIR" 2>&1 >&2; then
    echo "deploy-isolated.sh: wheel build failed" >&2
    exit 1
fi
WHEEL=$(ls "$WHEEL_DIR"/cove_cli-*.whl | head -1)
if [[ -z "$WHEEL" ]]; then
    echo "deploy-isolated.sh: no wheel produced" >&2
    exit 1
fi
echo "Built wheel: $(basename "$WHEEL")" >&2

STAGING_VENV="$REPO_ROOT/.staging-venv"
if [[ -d "$STAGING_VENV" ]]; then
    rm -rf "$STAGING_VENV"
fi
python3 -m venv "$STAGING_VENV"
"$STAGING_VENV/bin/pip" install --quiet "$WHEEL" jinja2

# --- Prepare the staging data tree (staging root only) -----------------------
echo "Preparing staging data root: $STAGING_DATA_ROOT" >&2
mkdir -p "$STAGING_DATA_ROOT"/{certs,dnsmasq,pages/sites,vault/data,vault/logs,ade,nginx/user.d,nginx/config/dns,nginx-conf}

# Certs: reuse the live mkcert pair if present (READ-only copy from the live
# root — never a mount, never a write). Otherwise generate a self-signed pair
# into the staging root. Never touches 1Password/biometric paths.
CERT_DIR="$STAGING_DATA_ROOT/certs"
if [[ -f "$LIVE_DATA_ROOT/certs/cove.local.pem" && -f "$LIVE_DATA_ROOT/certs/cove.local-key.pem" ]]; then
    cp "$LIVE_DATA_ROOT/certs/cove.local.pem" "$CERT_DIR/cove.local.pem"
    cp "$LIVE_DATA_ROOT/certs/cove.local-key.pem" "$CERT_DIR/cove.local-key.pem"
    echo "  certs: copied live mkcert pair (read-only copy)" >&2
else
    openssl req -x509 -newkey rsa:2048 -nodes -days 30 \
        -keyout "$CERT_DIR/cove.local-key.pem" -out "$CERT_DIR/cove.local.pem" \
        -subj "/CN=cove.local" \
        -addext "subjectAltName=DNS:cove.local,DNS:ade.cove,DNS:ade.cove.local,DNS:git.cove,DNS:git.cove.local,DNS:hc.cove,DNS:vault.cove,DNS:pages.cove,IP:127.0.0.1" \
        >/dev/null 2>&1
    echo "  certs: generated self-signed staging pair" >&2
fi
if [[ -f "$LIVE_DATA_ROOT/certs/rootCA.pem" ]]; then
    cp "$LIVE_DATA_ROOT/certs/rootCA.pem" "$CERT_DIR/rootCA.pem"
else
    cp "$CERT_DIR/cove.local.pem" "$CERT_DIR/rootCA.pem"
fi

# dnsmasq conf: copy the live rendered conf if present, else a minimal one.
if [[ -f "$LIVE_DATA_ROOT/dnsmasq/cove.conf" ]]; then
    cp "$LIVE_DATA_ROOT/dnsmasq/cove.conf" "$STAGING_DATA_ROOT/dnsmasq/cove.conf"
else
    printf 'address=/cove/127.0.0.1\n' > "$STAGING_DATA_ROOT/dnsmasq/cove.conf"
fi

# nginx config.html (bind target must be a file; empty is a valid 404 page state)
if [[ -f "$LIVE_DATA_ROOT/nginx/config.html" ]]; then
    cp "$LIVE_DATA_ROOT/nginx/config.html" "$STAGING_DATA_ROOT/nginx/config.html"
else
    : > "$STAGING_DATA_ROOT/nginx/config.html"
fi

# Staging nginx conf dir: static files from the branch + a fresh render of
# default.conf.j2 (staging render — the live conf is never touched).
NGINX_STAGING_CONF="$STAGING_DATA_ROOT/nginx-conf"
for f in landing.html pages.html cove-config-locations.conf cove-pages-locations.conf cove-tunnel-shares.conf; do
    cp "$COMPOSE_DIR/nginx/$f" "$NGINX_STAGING_CONF/$f"
done
"$STAGING_VENV/bin/python" - "$COMPOSE_DIR/nginx/default.conf.j2" "$NGINX_STAGING_CONF/default.conf" "$ADE_PORT" <<'PYEOF'
import sys
from jinja2 import Environment, FileSystemLoader

template_path, dest, ade_port = sys.argv[1], sys.argv[2], sys.argv[3]
env = Environment(loader=FileSystemLoader(str(__import__("pathlib").Path(template_path).parent)))
rendered = env.get_template("default.conf.j2").render({"ade_port": ade_port})
with open(dest, "w") as f:
    f.write(rendered)
PYEOF
echo "  nginx conf: rendered from branch template (ade_port=$ADE_PORT)" >&2

# --- Staging env file (absolute paths; compose env-file does not expand ~) ---
STAGING_ENV_FILE="$STAGING_DATA_ROOT/staging.env"
cat > "$STAGING_ENV_FILE" <<EOF
COVE_DATA_ROOT=$STAGING_DATA_ROOT
FORGEJO_DATA_ROOT=$STAGING_DATA_ROOT
NGINX_CONF_DIR=$NGINX_STAGING_CONF
ADE_PORT=$ADE_PORT
ADE_IMAGE=cove-ade-staging:\${ADE_BB_APP_VERSION:-0.43.4}
STAGING_NGINX_HTTPS_PORT=$STAGING_HTTPS_PORT
EOF
echo "  env file: $STAGING_ENV_FILE" >&2

# --- Bring up the isolated project -------------------------------------------
COMPOSE_CMD=(docker compose -p "$STAGING_PROJECT"
    --env-file "$STAGING_ENV_FILE"
    --project-directory "$COMPOSE_DIR"
    -f "$COMPOSE_DIR/docker-compose.yml"
    -f "$COMPOSE_DIR/docker-compose.staging.yml"
    )

echo "Bringing up $STAGING_PROJECT (build may take a few minutes on first run)..." >&2
if ! "${COMPOSE_CMD[@]}" up -d --build 2>&1 >&2; then
    echo "deploy-isolated.sh: compose up failed" >&2
    "${COMPOSE_CMD[@]}" ps -a 2>&1 >&2 || true
    exit 1
fi

# --- Wait for health (fail loud on timeout) -----------------------------------
STAGING_URL="https://127.0.0.1:$STAGING_HTTPS_PORT"
check_health() {
    docker inspect -f '{{.State.Running}}' "cove-staging-nginx" 2>/dev/null | grep -q '^true$' \
        && curl -sf -k --max-time 5 -H "Host: cove.local" "$STAGING_URL/_health" 2>/dev/null | grep -q '^ok$' \
        && curl -sf -k --max-time 5 -H "Host: ade.cove" "$STAGING_URL/health" 2>/dev/null | grep -q '"ok"'
}

HEALTH_TIMEOUT="${STAGING_HEALTH_TIMEOUT:-600}"
echo "Waiting up to ${HEALTH_TIMEOUT}s for nginx + ade health..." >&2
deadline=$((SECONDS + HEALTH_TIMEOUT))
until check_health; do
    if (( SECONDS >= deadline )); then
        echo "deploy-isolated.sh: staging did not become healthy within ${HEALTH_TIMEOUT}s" >&2
        echo "--- compose ps ---" >&2
        "${COMPOSE_CMD[@]}" ps -a 2>&1 >&2 || true
        echo "--- cove-staging-nginx logs (last 30) ---" >&2
        docker logs --tail 30 cove-staging-nginx 2>&1 >&2 || true
        echo "--- cove-staging-ade-server logs (last 30) ---" >&2
        docker logs --tail 30 cove-staging-ade-server 2>&1 >&2 || true
        exit 1
    fi
    sleep 5
done
echo "Staging healthy." >&2

# Only stdout line consumed by e2e.sh
echo "$STAGING_URL"
