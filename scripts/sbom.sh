#!/usr/bin/env bash
# Generate CycloneDX SBOM snapshots for the cove stack.
#
# Usage: scripts/sbom.sh [COMPONENT ...]
#
# COMPONENT names match the `name` column of `cove --sbom` (from cove.pins).
# With no arguments every image-kind pin is processed. Bases built from
# Dockerfiles are skipped: their packages are covered by the image SBOMs.
# Output: sbom/<component>.cdx.json (repo-root, committed at bump time).
#
# Requires: trivy on PATH, docker (images present locally), python3 + uv.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

command -v trivy >/dev/null || { echo "trivy is not on PATH (brew install trivy)" >&2; exit 1; }
command -v uv >/dev/null || { echo "uv is not on PATH" >&2; exit 1; }

INVENTORY_JSON="$(uv run --directory cli python -m cove.pins "$REPO_ROOT/compose")"
mkdir -p sbom

COMPONENTS=("$@")
if [ ${#COMPONENTS[@]} -eq 0 ]; then
  mapfile -t COMPONENTS < <(
    python3 -c "
import json, sys
inventory = json.loads('''${INVENTORY_JSON}''')
for pin in inventory:
    if pin['kind'] == 'image':
        print(pin['name'])
"
  )
fi

if [ ${#COMPONENTS[@]} -eq 0 ]; then
  echo "no image-kind pins found in compose/ inventory" >&2
  exit 1
fi

failures=()
for component in "${COMPONENTS[@]}"; do
  ref="$(python3 -c "
import json
inventory = json.loads('''${INVENTORY_JSON}''')
match = [p['ref'] for p in inventory if p['name'] == '''${component}''' and p['kind'] == 'image']
if len(match) != 1:
    print('MISSING', len(match), file=sys.stderr); sys.exit(1)
print(match[0])
")"
  out="sbom/${component}.cdx.json"
  echo "SBOM: ${component} <-- ${ref}"
  if ! trivy image --format cyclonedx --output "$out" "$ref"; then
    failures+=("$component")
    echo "FAILED: ${component}" >&2
  fi
done

if [ ${#failures[@]} -gt 0 ]; then
  echo "completed with failures: ${failures[*]}" >&2
  exit 1
fi
echo "all requested SBOM snapshots written to sbom/"