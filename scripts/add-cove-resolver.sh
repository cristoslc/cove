#!/bin/bash
set -euo pipefail

echo "Creating macOS resolver for cove.local..."

sudo mkdir -p /etc/resolver
sudo tee /etc/resolver/cove.local > /dev/null << 'EOF'
nameserver 127.0.0.1
port 5353
EOF

echo "Resolver /etc/resolver/cove.local created."

echo "Removing old cove hosts entries from /etc/hosts..."
sudo sed -i '' '/cove\.mbpbk-202602\.taila90e7\.ts\.net/d' /etc/hosts 2>/dev/null || true
sudo sed -i '' '/git\.cove\.mbpbk/d' /etc/hosts 2>/dev/null || true

echo "Done. DNS for *.cove.local now resolves via dnsmasq on 127.0.0.1:5353."