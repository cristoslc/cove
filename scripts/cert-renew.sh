#!/usr/bin/env bash
set -euo pipefail

FQDN="mbpbk-202602.taila90e7.ts.net"
CERTS_DIR="${FORGEJO_DATA_ROOT:-$HOME/Documents/cove-data}/certs"
CONTAINER="cove-forgejo"

echo "Renewing TLS certificate for $FQDN..."
tailscale cert \
    --cert-file "$CERTS_DIR/fullchain.pem" \
    --key-file "$CERTS_DIR/privkey.pem" \
    "$FQDN"

if docker ps -q -f name="$CONTAINER" | grep -q .; then
    echo "Restarting $CONTAINER to pick up new cert..."
    docker restart "$CONTAINER"
    echo "Done. Certificate renewed."
else
    echo "Container not running — cert will be picked up on next start."
fi
