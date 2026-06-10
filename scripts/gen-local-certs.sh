#!/usr/bin/env bash
set -euo pipefail

COVE_DATA_ROOT="${COVE_DATA_ROOT:-$HOME/Documents/cove-data}"
CERT_DIR="$COVE_DATA_ROOT/certs"
COVE_DOMAIN="${COVE_DOMAIN:-cove.local}"

if ! command -v mkcert &>/dev/null; then
    echo "mkcert not found. Installing via Homebrew..."
    brew install mkcert
fi

mkcert -install

mkdir -p "$CERT_DIR"
mkcert \
    -key-file "$CERT_DIR/privkey.pem" \
    -cert-file "$CERT_DIR/fullchain.pem" \
    "*.$COVE_DOMAIN" \
    "git.$COVE_DOMAIN"

echo "Certificates generated in $CERT_DIR"
echo "  *.${COVE_DOMAIN}"
echo "  git.${COVE_DOMAIN}"