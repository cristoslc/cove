#!/bin/bash
set -euo pipefail

HOSTS_ENTRIES=(
  "127.0.0.1 git.cove.mbpbk-202602.taila90e7.ts.net"
)

for entry in "${HOSTS_ENTRIES[@]}"; do
  hostname=$(echo "$entry" | awk '{print $2}')
  if grep -q "$hostname" /etc/hosts 2>/dev/null; then
    echo "Already present: $hostname"
  else
    echo "$entry" | sudo tee -a /etc/hosts > /dev/null
    echo "Added: $entry"
  fi
done