#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
COVE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_DIR="$COVE_DIR/compose"
CERTS_DIR="$COMPOSE_DIR/certs"
SSH_DIR="$COMPOSE_DIR/data/forgejo/ssh"
GITEA_DIR="$COMPOSE_DIR/data/forgejo/gitea"
GIT_DIR="$COMPOSE_DIR/data/forgejo/git"
OLD_CONTAINER="local-pod-forgejo"
NEW_CONTAINER="cove-forgejo"
FQDN="mbpbk-202602.taila90e7.ts.net"
HOSTS_LINE="127.0.0.1 $FQDN"

echo "=== Cove Forgejo Migration ==="
echo ""

# --- Step 1: Generate Tailscale TLS certificate ---
echo "[1/6] Generating TLS certificate for $FQDN..."
mkdir -p "$CERTS_DIR"

if tailscale cert \
    --cert-file "$CERTS_DIR/fullchain.pem" \
    --key-file "$CERTS_DIR/privkey.pem" \
    "$FQDN"; then
    echo "  Certificate generated."
else
    echo "  ERROR: tailscale cert failed. Is MagicDNS + HTTPS enabled in Tailscale admin console?"
    exit 1
fi

# --- Step 2: Verify /etc/hosts entry ---
echo "[2/6] Checking /etc/hosts entry for $FQDN..."
if grep -q "^$HOSTS_LINE" /etc/hosts 2>/dev/null; then
    echo "  Already present."
else
    echo "  *** Run this manually: sudo -- sh -c 'echo \"$HOSTS_LINE\" >> /etc/hosts' ***"
    echo "  WARNING: /etc/hosts entry missing. The FQDN won't resolve locally."
fi

# --- Step 3: Extract SSH host keys from running old container ---
echo "[3/6] Extracting SSH host keys from running container..."
mkdir -p "$SSH_DIR" "$GITEA_DIR" "$GIT_DIR"

if docker ps -q -f name="$OLD_CONTAINER" | grep -q .; then
    for KEY in ssh_host_ed25519_key ssh_host_rsa_key ssh_host_ecdsa_key; do
        docker cp "$OLD_CONTAINER:/data/ssh/$KEY" "$SSH_DIR/$KEY" 2>/dev/null || true
        if [ -f "$SSH_DIR/$KEY" ]; then
            chmod 600 "$SSH_DIR/$KEY"
            echo "  Extracted $KEY"
        fi
    done
else
    echo "  WARNING: Old container not running. SSH host keys will be regenerated."
fi

# --- Step 4: Stop old Forgejo container ---
echo "[4/6] Stopping old Forgejo container..."
if docker ps -q -f name="$OLD_CONTAINER" | grep -q .; then
    docker stop "$OLD_CONTAINER"
    echo "  Stopped."
else
    echo "  Not running."
fi

# --- Step 5: Copy and restructure data ---
echo "[5/6] Copying and restructuring Forgejo data..."
DATA_SRC="/Users/cristos/Documents/local-pod-data/forgejo/data"

if [ -d "$DATA_SRC" ]; then
    # v10 layout: data/data/gitea.db, data/git/repositories/
    # v15 layout: /data/gitea/gitea.db, /data/git/repositories/
    sudo rsync -a --info=progress2 "$DATA_SRC/" "$GITEA_DIR/"
    mkdir -p "$GIT_DIR"

    if [ -f "$GITEA_DIR/data/gitea.db" ]; then
        mv "$GITEA_DIR/data/gitea.db" "$GITEA_DIR/gitea.db"
    fi

    if [ -d "$GITEA_DIR/git/repositories" ]; then
        mv "$GITEA_DIR/git/repositories" "$GIT_DIR/repositories"
    fi

    # Clean up nested structure
    rm -rf "$GITEA_DIR/data" "$GITEA_DIR/git" "$GITEA_DIR/log" 2>/dev/null || true

    sudo chown -R "$(id -u):$(id -g)" "$COMPOSE_DIR/data"
    echo "  Data copied and restructured."
else
    echo "  ERROR: No data found at $DATA_SRC"
    exit 1
fi

# --- Step 6: Start new Forgejo container ---
echo "[6/6] Starting Cove Forgejo..."
cd "$COMPOSE_DIR"
docker compose up -d

echo ""
echo "=== Migration complete ==="
echo ""
echo "  URL:    https://$FQDN:3000"
echo "  SSH:    ssh://git@$FQDN:2222"
echo ""
echo "Check logs:  docker logs -f $NEW_CONTAINER"
echo "Smoke test:  curl -k https://$FQDN:3000/api/forgejo/v1/version"
echo ""
echo "Old container ($OLD_CONTAINER) is stopped but not removed."
echo "To fully decommission, run:  scripts/teardown-old.sh"
