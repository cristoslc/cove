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
# Branch compose profiles the isolated stack should start (detected below).
MCP_PROFILE=false

# --- Safety guards: the staging root must never be the live root -------------
if [[ "$STAGING_DATA_ROOT" == "$LIVE_DATA_ROOT" ]]; then
    echo "deploy-isolated.sh: SAFETY VIOLATION — staging data root equals live root ($LIVE_DATA_ROOT)" >&2
    exit 1
fi
STAGING_DATA_ROOT_REAL=$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$STAGING_DATA_ROOT")
LIVE_DATA_ROOT_REAL=$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$LIVE_DATA_ROOT")
if ! python3 - "$STAGING_DATA_ROOT_REAL" "$LIVE_DATA_ROOT_REAL" <<'PYEOF'
import os
import sys

staging_root, live_root = sys.argv[1:]
common = os.path.commonpath((staging_root, live_root))
sys.exit(1 if common in (staging_root, live_root) else 0)
PYEOF
then
    echo "deploy-isolated.sh: SAFETY VIOLATION — staging and live data roots overlap ($STAGING_DATA_ROOT_REAL, $LIVE_DATA_ROOT_REAL)" >&2
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
echo "  nginx:        https://127.0.0.1:$STAGING_HTTPS_PORT (Host: ade.cove, mcp.cove)" >&2
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
mkdir -p "$STAGING_DATA_ROOT"/{certs,dnsmasq,pages/sites,vault/data,vault/logs,ade,nginx/user.d,nginx/config/dns,nginx-conf,toolhive/config,toolhive/state,toolhive/profiles}

# LiteLLM's generated YAML is readable by container UID 1000, so keep its
# parent directory private on the host. Provider values remain in this 0600
# env file and are never copied into config.yaml.
"$STAGING_VENV/bin/python" "$COMPOSE_DIR/litellm/config_overlay.py" --ensure-private-dir "$STAGING_DATA_ROOT/litellm" --trusted-root "$STAGING_DATA_ROOT" >/dev/null
"$STAGING_VENV/bin/python" "$COMPOSE_DIR/litellm/config_overlay.py" --ensure-env-file "$STAGING_DATA_ROOT/litellm/local.env" --trusted-root "$STAGING_DATA_ROOT" >/dev/null

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
# default.conf.j2 and the llmproxy edge auth include (staging render — the live
# conf is never touched). The staging edge token is generated per deploy: it is
# a local test credential, never the live client token.
NGINX_STAGING_CONF="$STAGING_DATA_ROOT/nginx-conf"
for f in landing.html pages.html cove-config-locations.conf cove-pages-locations.conf cove-tunnel-shares.conf; do
    cp "$COMPOSE_DIR/nginx/$f" "$NGINX_STAGING_CONF/$f"
done
STAGING_LLMPROXY_CLIENT_KEY="sk-staging-$(openssl rand -hex 16)"
export STAGING_LLMPROXY_CLIENT_KEY
"$STAGING_VENV/bin/python" - "$COMPOSE_DIR/nginx" "$NGINX_STAGING_CONF" "$ADE_PORT" <<'PYEOF'
import os
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

src_dir, dest_dir, ade_port = sys.argv[1], sys.argv[2], sys.argv[3]
env = Environment(loader=FileSystemLoader(src_dir))
default = env.get_template("default.conf.j2").render({"ade_port": ade_port})
Path(dest_dir, "default.conf").write_text(default)
auth = env.get_template("llmproxy-auth.conf.j2").render({
    "llmproxy_client_key": os.environ["STAGING_LLMPROXY_CLIENT_KEY"],
    # Staging has no real backends; these placeholders never leave the
    # isolated staging project.
    "llmproxy_litellm_key": "sk-staging-litellm",
    "llmproxy_bifrost_key": "sk-staging-bifrost",
})
auth_path = Path(dest_dir, "llmproxy-auth.conf")
auth_path.write_text(auth)
auth_path.chmod(0o600)
PYEOF
echo "  nginx conf: rendered from branch template (ade_port=$ADE_PORT; llmproxy edge auth 0600)" >&2

# ToolHive seed (staging root only; mirrors bringup.yml first-boot copies):
# curated registry, default permission profile, and the control-plane config
# pointing the API server at the local registry (remote fetch stays off).
# registry.json MUST be a file before compose up — Docker would otherwise
# auto-create a directory and wedge the read-only mount.
if [[ -f "$COMPOSE_DIR/toolhive/registry.json" ]]; then
    cp "$COMPOSE_DIR/toolhive/registry.json" "$STAGING_DATA_ROOT/toolhive/registry.json"
    cp "$COMPOSE_DIR/toolhive/cove-default.json" "$STAGING_DATA_ROOT/toolhive/profiles/cove-default.json"
    "$STAGING_VENV/bin/python" - "$COMPOSE_DIR/toolhive/config.yaml.j2" "$STAGING_DATA_ROOT/toolhive/config/toolhive/config.yaml" <<'PYEOF'
import os
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

template_path, dest = sys.argv[1], sys.argv[2]
env = Environment(loader=FileSystemLoader(str(Path(template_path).parent)))
rendered = env.get_template("config.yaml.j2").render({})
os.makedirs(os.path.dirname(dest), exist_ok=True)
with open(dest, "w") as f:
    f.write(rendered)
PYEOF
    echo "  toolhive: registry/profiles/config seeded (staging root only)" >&2
fi

# --- Runner config: never share the live compose network ---------------------
# compose/forgejo-runner/config.yml hardcodes `container.network: cove_default`,
# which is the LIVE project's network. A staging runner loaded from that file
# spawns its job containers on the live network. Render a per-project copy and
# mount it over /config.yml through a data-root override file, so the repo
# file stays the live contract and staging never joins the live network.
STAGING_RUNNER_DIR="$STAGING_DATA_ROOT/forgejo-runner"
STAGING_RUNNER_CONFIG="$STAGING_RUNNER_DIR/config.yml"
mkdir -p "$STAGING_RUNNER_DIR"
sed "s|^  network:.*|  network: \"${STAGING_PROJECT}_default\"|" \
    "$COMPOSE_DIR/forgejo-runner/config.yml" > "$STAGING_RUNNER_CONFIG"
if ! grep -qx "  network: \"${STAGING_PROJECT}_default\"" "$STAGING_RUNNER_CONFIG"; then
    echo "deploy-isolated.sh: could not pin the runner network to ${STAGING_PROJECT}_default in $STAGING_RUNNER_CONFIG" >&2
    exit 1
fi

STAGING_COMPOSE_OVERRIDE="$STAGING_DATA_ROOT/compose-override.yml"
cat > "$STAGING_COMPOSE_OVERRIDE" <<EOF
# Generated by deploy-isolated.sh. Staging-only; never mounted by the live project.
#
# The base compose file declares the live project's subnets so nginx can sit on
# a fixed address (172.28.0.0/24 for the ingress, 172.43.0.0/24 for the bifrost
# egress boundary). A second project may not hold the same subnet, so staging
# gets its own pair. The ingress subnet must also stay inside the nginx
# private-range ACL (10/8, 172.16/12, 192.168/16, 100.64/10), or the ade.cove
# and bifrost.cove vhosts answer 403 to every request. NGINX_IP and
# FORGEJO_TRUSTED_PROXY in staging.env point at the staging ingress address,
# not the live one.
networks:
  default:
    ipam:
      config:
        - subnet: 172.29.0.0/24
  bifrost-egress:
    ipam:
      config:
        - subnet: 172.46.0.0/24
services:
  forgejo-runner:
    volumes:
      - $STAGING_RUNNER_CONFIG:/config.yml:ro
  bifrost-dns:
    networks:
      bifrost-egress:
        ipv4_address: 172.46.0.10
EOF
echo "  runner: config rendered for network ${STAGING_PROJECT}_default (override: $STAGING_COMPOSE_OVERRIDE)" >&2

# --- Runner socket gid -------------------------------------------------------
# The runner image runs as uid 1000 and the Colima socket is root:root 660. The
# live .env pins the gid; the compose default (991) is wrong here and shows up
# as a crash loop with "permission denied ... /var/run/docker.sock". Resolve the
# value from the environment, then the live .env, then a read-only socket probe
# as a container sees it (same mount the runner gets).
STAGING_RUNNER_DOCKER_GID="${FORGEJO_RUNNER_DOCKER_GID:-}"
if [[ -z "$STAGING_RUNNER_DOCKER_GID" && -f "$HOME/.config/cove/compose/.env" ]]; then
    STAGING_RUNNER_DOCKER_GID=$(sed -n 's/^FORGEJO_RUNNER_DOCKER_GID=//p' \
        "$HOME/.config/cove/compose/.env" | tail -1)
fi
if [[ -z "$STAGING_RUNNER_DOCKER_GID" ]]; then
    STAGING_RUNNER_DOCKER_GID=$(docker run --rm \
        -v /var/run/docker.sock:/var/run/docker.sock \
        --entrypoint stat alpine:3.21 -c '%g' /var/run/docker.sock 2>/dev/null || true)
fi
if [[ -z "$STAGING_RUNNER_DOCKER_GID" ]]; then
    echo "deploy-isolated.sh: could not determine the docker socket gid; the runner profile would not reach the socket" >&2
    exit 1
fi

# --- Staging env file (absolute paths; compose env-file does not expand ~) ---
STAGING_ENV_FILE="$STAGING_DATA_ROOT/staging.env"
cat > "$STAGING_ENV_FILE" <<EOF
COVE_DATA_ROOT=$STAGING_DATA_ROOT
FORGEJO_DATA_ROOT=$STAGING_DATA_ROOT
NGINX_CONF_DIR=$NGINX_STAGING_CONF
ADE_PORT=$ADE_PORT
ADE_IMAGE=cove-ade-staging:\${ADE_BB_APP_VERSION:-0.43.4}
STAGING_NGINX_HTTPS_PORT=$STAGING_HTTPS_PORT
FORGEJO_ROOT_URL=https://git.cove.local:$STAGING_HTTPS_PORT/
FORGEJO_DOMAIN=git.cove.local
FORGEJO_SSH_DOMAIN=git.cove.local
FORGEJO_RUNNER_DOCKER_GID=$STAGING_RUNNER_DOCKER_GID
NGINX_IP=172.29.0.10
FORGEJO_TRUSTED_PROXY=172.29.0.10
EOF
echo "  env file: $STAGING_ENV_FILE" >&2

# --- Bring up the isolated project -------------------------------------------
COMPOSE_CMD=(docker compose -p "$STAGING_PROJECT"
    --env-file "$STAGING_ENV_FILE"
    --project-directory "$COMPOSE_DIR"
    -f "$COMPOSE_DIR/docker-compose.yml"
    -f "$COMPOSE_DIR/docker-compose.staging.yml"
    -f "$STAGING_COMPOSE_OVERRIDE"
    )

# Start any branch compose profiles the staging E2E needs — same grep pattern
# deploy.sh uses, but scoped to the ISOLATED project render so the live stack
# is never touched. If the branch declares the mcp profile, the toolhive
# staging instance comes up alongside ade (its e2e module requires it).
if "${COMPOSE_CMD[@]}" config --profiles 2>/dev/null | grep -qx "mcp"; then
    echo "Branch declares the mcp profile — starting toolhive in the staging project" >&2
    MCP_PROFILE=true
    COMPOSE_CMD+=(--profile mcp)
fi

# --- Staging network subnet migration ----------------------------------------
# Compose does not recreate an existing network when its IPAM config changes.
# A staging stack created before the subnet split keeps its old dynamic subnet,
# and the pinned nginx address then fails with "no configured subnet contains IP
# address". Recreate only the staging project (and its network) when the subnet
# does not match. Bind-mounted data and named volumes survive: no `-v`.
STAGING_SUBNET="172.29.0.0/24"
STAGING_NETWORK="${STAGING_PROJECT}_default"
CURRENT_SUBNET=$(docker network inspect "$STAGING_NETWORK" \
    --format '{{range .IPAM.Config}}{{.Subnet}}{{end}}' 2>/dev/null || true)
if [[ -n "$CURRENT_SUBNET" && "$CURRENT_SUBNET" != "$STAGING_SUBNET" ]]; then
    echo "Staging network $STAGING_NETWORK is $CURRENT_SUBNET, expected $STAGING_SUBNET: recreating the staging project's network" >&2
    # Every profile, because the runner lives behind its own profile and a
    # container still attached blocks the network removal. `down` usually
    # removes the project network itself, so only remove what survives.
    "${COMPOSE_CMD[@]}" --profile "*" down --remove-orphans >/dev/null 2>&1 || true
    if docker network inspect "$STAGING_NETWORK" >/dev/null 2>&1; then
        for _ in 1 2 3 4 5; do
            docker network rm "$STAGING_NETWORK" >/dev/null 2>&1 && break
            sleep 1
        done
        if docker network inspect "$STAGING_NETWORK" >/dev/null 2>&1; then
            echo "deploy-isolated.sh: could not remove $STAGING_NETWORK; run scripts/staging/teardown.sh and retry" >&2
            exit 1
        fi
    fi
fi

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
        if [[ "$MCP_PROFILE" == true ]]; then
            echo "--- cove-staging-toolhive logs (last 30) ---" >&2
            docker logs --tail 30 cove-staging-toolhive 2>&1 >&2 || true
        fi
        exit 1
    fi
    sleep 5
done
echo "Staging healthy." >&2

# --- Optional ToolHive health (mcp profile only) ------------------------------
# The base stack above is the deploy contract. ToolHive is an optional service,
# and its staging instance needs a working container runtime inside the compose
# network; when it cannot get one it crash-loops. Gating the whole deploy on it
# turned a working nginx/ade/forgejo stack into a 600s wait and exit 1. Wait a
# bounded time, report loudly, and keep the exit status truthful for the base
# stack. STAGING_REQUIRE_MCP_HEALTH=1 restores the fatal gate for CI.
if [[ "$MCP_PROFILE" == true ]]; then
    MCP_TIMEOUT="${STAGING_MCP_HEALTH_TIMEOUT:-120}"
    echo "Waiting up to ${MCP_TIMEOUT}s for toolhive health (mcp profile)..." >&2
    mcp_deadline=$((SECONDS + MCP_TIMEOUT))
    mcp_healthy=false
    while (( SECONDS < mcp_deadline )); do
        if docker inspect -f '{{.State.Health.Status}}' "cove-staging-toolhive" 2>/dev/null | grep -q '^healthy$'; then
            mcp_healthy=true
            break
        fi
        sleep 5
    done
    if [[ "$mcp_healthy" != true ]]; then
        echo "WARNING: cove-staging-toolhive is not healthy after ${MCP_TIMEOUT}s. nginx, ade and forgejo are up and the staging URL is valid; the toolhive staging E2E will fail until this is fixed. Set STAGING_REQUIRE_MCP_HEALTH=1 to make this fatal." >&2
        docker logs --tail 10 cove-staging-toolhive 2>&1 >&2 || true
        if [[ "${STAGING_REQUIRE_MCP_HEALTH:-0}" == "1" ]]; then
            echo "deploy-isolated.sh: STAGING_REQUIRE_MCP_HEALTH=1 and toolhive is unhealthy" >&2
            exit 1
        fi
    fi
fi

# Only stdout line consumed by e2e.sh
echo "$STAGING_URL"
