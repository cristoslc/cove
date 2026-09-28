#!/usr/bin/env bash
# Dual-host release publisher: GitHub (cristoslc/cove) + Forgejo (git.cove/cristos/cove).
#
# Releases MUST land on both remotes with the wheel attached — see
# docs/tech-debt/dual-host-release-drift.md and the Promote section in AGENTS.md.
#
# Usage:
#   scripts/release.sh <version>        e.g. scripts/release.sh 0.9.2
#
# Prerequisites:
#   - The promote build has run (AGENTS.md): sync_compose_resources.py +
#     `uv build --wheel --out-dir cli/dist` from cli/ — this script expects
#     cli/dist/cove_cli-<version>-py3-none-any.whl to exist.
#   - A `## <version>` section exists in CHANGELOG.md (it becomes the notes).
#   - The annotated tag v<version> exists locally.
#   - `gh` authed for github.com; `fj` authed for git.cove.
#
# Idempotent: releases that already exist on a host are detected and skipped
# (so re-running after a partial failure only fills the gaps).
set -euo pipefail
cd "$(dirname "$0")/.."

VER="${1:?usage: scripts/release.sh <version> (e.g. 0.9.2)}"
TAG="v${VER}"
WHEEL="cli/dist/cove_cli-${VER}-py3-none-any.whl"

if [[ ! -f "$WHEEL" ]]; then
  echo "error: wheel missing at $WHEEL" >&2
  echo "  run the promote build first (see AGENTS.md: sync_compose_resources.py + uv build --wheel)" >&2
  exit 1
fi

NOTES="$(awk -v ver="$VER" '$0 ~ "^## "ver {f=1;next} f&&/^## /{f=0} f' CHANGELOG.md)"
if [[ -z "$NOTES" ]]; then
  echo "error: no '## ${VER}' section in CHANGELOG.md" >&2
  exit 1
fi

echo "==> Pushing tag ${TAG} to both remotes..."
git push origin "$TAG"
git push github "$TAG"

echo "==> GitHub release..."
if gh release view "$TAG" --repo cristoslc/cove >/dev/null 2>&1; then
  echo "    release $TAG exists — ensuring wheel attached"
  gh release upload "$TAG" --repo cristoslc/cove --clobber "$WHEEL"
else
  gh release create "$TAG" --repo cristoslc/cove \
    --title "cove-cli ${VER}" --notes "$NOTES" "$WHEEL"
fi

echo "==> Forgejo release (git.cove)..."
if fj -H git.cove release view "$VER" >/dev/null 2>&1; then
  echo "    release $VER exists — skipped (delete it first to re-attach assets)"
else
  fj -H git.cove release create "$VER" -t "$TAG" -b "$NOTES" -a "$WHEEL"
fi

echo "==> ${VER} published to GitHub and Forgejo."
