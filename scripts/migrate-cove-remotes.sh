#!/usr/bin/env bash
# migrate-cove-remotes.sh — Update external repos from git.cove to git.cove.local
#
# Usage:
#   bash migrate-cove-remotes.sh          # dry-run (default)
#   bash migrate-cove-remotes.sh --exec    # execute changes
#   bash migrate-cove-remotes.sh --exec --ssh  # execute + update known_hosts
#
# Safe: dry-run by default. Each repo is processed atomically.
# Reversible: `git remote set-url` is purely local.
# Uses perl negative lookahead to avoid double-replacing git.cove → git.cove.local.local.

set -euo pipefail

EXEC=false
UPDATE_SSH=false
for arg in "$@"; do
  case "$arg" in
    --exec) EXEC=true ;;
    --ssh) UPDATE_SSH=true ;;
  esac
done

REPOS=(
  "$HOME/code/ai-harness-hooks"
  "$HOME/code/ai-montage"
  "$HOME/code/ai-usage-cost-analysis"
  "$HOME/code/opencode-ds4-proxy"
  "$HOME/code/orbic-rc400l-cli"
  "$HOME/code/swain-box"
  "$HOME/code/swain-phone"
  "$HOME/code/swain-v2"
  "$HOME/code/vendor-canary"
  "$HOME/projects/common-bell-research"
  "$HOME/projects/llm-data-export-manager"
)

# Project Hal has a space in the path
if [ -d "$HOME/projects/Project Hal" ]; then
  REPOS+=("$HOME/projects/Project Hal")
fi

# First pass: fix any mangled URLs (git.cove.local.local → git.cove.local)
# Second pass: replace git.cove → git.cove.local (only when not already .local)
# Uses perl negative lookahead: git.cove NOT followed by .local

updated_remotes=0
updated_agents=0
updated_files=0
errors=0

for repo in "${REPOS[@]}"; do
  if [ ! -d "$repo/.git" ] && [ ! -f "$repo/.git" ]; then
    echo "[SKIP] $repo — not a git repo"
    continue
  fi

  echo ""
  echo "=== $repo ==="

  # --- Fix mangled URLs (git.cove.local.local → git.cove.local) ---
  while IFS= read -r line; do
    name=$(echo "$line" | awk '{print $1}')
    old_url=$(echo "$line" | awk '{print $2}')
    if [[ "$old_url" == *"git.cove.local.local"* ]]; then
      new_url="${old_url//git.cove.local.local/git.cove.local}"
      if [ "$EXEC" = true ]; then
        git -C "$repo" remote set-url "$name" "$new_url"
        echo "  [FIX] remote $name: $old_url → $new_url"
      else
        echo "  [DRY] remote $name: $old_url → $new_url (fix mangled)"
      fi
      updated_remotes=$((updated_remotes + 1))
    fi
  done < <(git -C "$repo" remote -v 2>/dev/null | grep "git.cove" || true)

  # --- Fix mangled URLs in files ---
  while IFS= read -r f; do
    [ -z "$f" ] && continue
    rel="${f#$repo/}"
    if [ "$EXEC" = true ]; then
      perl -i -pe 's/git\.cove\.local\.local/git.cove.local/g' "$f"
      echo "  [FIX] $rel: fixed mangled URL"
    else
      echo "  [DRY] $rel: would fix mangled URL"
    fi
    updated_files=$((updated_files + 1))
  done < <(grep -rl "git.cove.local.local" "$repo" --include="*.md" --include="*.py" --include="*.yaml" --include="*.yml" --include="*.json" --include="*.cfg" --include="*.conf" --include="*.toml" 2>/dev/null | grep -v ".git/" || true)

  # --- Git remotes (main migration) ---
  while IFS= read -r line; do
    name=$(echo "$line" | awk '{print $1}')
    old_url=$(echo "$line" | awk '{print $2}')
    # Only replace if git.cove is NOT already followed by .local
    if echo "$old_url" | grep -q 'git\.cove\.'; then
      # Already has something after git.cove (like git.cove.local or git.cove.something)
      # Skip — only migrate bare git.cove
      continue
    fi
    new_url="${old_url//git.cove/git.cove.local}"
    if [ "$new_url" != "$old_url" ]; then
      if [ "$EXEC" = true ]; then
        git -C "$repo" remote set-url "$name" "$new_url"
        echo "  [OK] remote $name: $old_url → $new_url"
      else
        echo "  [DRY] remote $name: $old_url → $new_url"
      fi
      updated_remotes=$((updated_remotes + 1))
    fi
  done < <(git -C "$repo" remote -v 2>/dev/null | grep "git.cove" || true)

  # --- AGENTS.md ---
  agents="$repo/AGENTS.md"
  if [ -f "$agents" ] && grep -q "git.cove\|vault.cove" "$agents" 2>/dev/null; then
    if [ "$EXEC" = true ]; then
      perl -i -pe 's/git\.cove(?!\.local)/git.cove.local/g; s/vault\.cove(?!\.local)/vault.cove.local/g' "$agents"
      echo "  [OK] AGENTS.md: updated"
    else
      echo "  [DRY] AGENTS.md: would update"
      grep -n "git.cove\|vault.cove" "$agents" || true
    fi
    updated_agents=$((updated_agents + 1))
  else
    echo "  AGENTS.md: no git.cove references"
  fi

  # --- Other files with hardcoded URLs ---
  while IFS= read -r f; do
    [ -z "$f" ] && continue
    rel="${f#$repo/}"
    if [ "$EXEC" = true ]; then
      perl -i -pe 's/git\.cove(?!\.local)/git.cove.local/g; s/vault\.cove(?!\.local)/vault.cove.local/g' "$f"
      echo "  [OK] $rel: updated"
    else
      echo "  [DRY] $rel: would update"
    fi
    updated_files=$((updated_files + 1))
  done < <(grep -rlP "git\.cove(?!\.local)" "$repo" --include="*.md" --include="*.py" --include="*.yaml" --include="*.yml" --include="*.json" --include="*.cfg" --include="*.conf" --include="*.toml" 2>/dev/null | grep -v "AGENTS.md" | grep -v ".git/" || true)
done

# --- SSH known_hosts ---
if [ "$UPDATE_SSH" = true ] && [ "$EXEC" = true ]; then
  echo ""
  echo "=== SSH known_hosts ==="
  ssh-keygen -R "git.cove" 2>/dev/null && echo "  [OK] removed git.cove from known_hosts" || echo "  [SKIP] git.cove not in known_hosts"
  ssh-keygen -R "git.cove.local" 2>/dev/null || true
  ssh-keyscan -H "git.cove.local" >> "$HOME/.ssh/known_hosts" 2>/dev/null && echo "  [OK] added git.cove.local to known_hosts" || echo "  [WARN] could not scan git.cove.local (is cove up?)"
fi

# --- Summary ---
echo ""
echo "========================================"
echo "Summary:"
echo "  Remotes updated:  $updated_remotes"
echo "  AGENTS.md files:  $updated_agents"
echo "  Other files:      $updated_files"
echo "  Errors:           $errors"
echo "  Mode:             $([ "$EXEC" = true ] && echo 'EXECUTE' || echo 'DRY-RUN')"
echo "  SSH known_hosts:  $([ "$UPDATE_SSH" = true ] && echo 'yes' || echo 'no')"
echo "========================================"
echo ""
echo "Run with --exec to apply changes."
echo "Run with --exec --ssh to also update known_hosts."
