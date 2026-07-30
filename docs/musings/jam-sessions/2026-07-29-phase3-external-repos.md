# Jam: Phase 3 — External Repo Updates

Updating 12+ external repos from `git.cove` to `git.cove.local` remotes.

## 2026-07-29 — Initial exploration

- **Problem:** These are separate git repos, not branches in the cove repo. Can't use worktree/sashay.
- **Approach:** Write a single script that iterates over all repos, updates remotes, AGENTS.md, and hardcoded URLs.
- **Key constraint:** Must be safe — dry-run first, atomic per-repo changes, no destructive operations.

## 2026-07-29 — Execution

- **Script:** `scripts/migrate-cove-remotes.sh` — dry-run by default, `--exec` to apply, `--ssh` for known_hosts
- **Lesson learned:** Naive `sed` replacement double-replaced `git.cove` → `git.cove.local` → `git.cove.local.local` on second run. Fixed with `perl` negative lookahead regex and a separate fix-mangled pass.
- **Lesson learned:** Space in "Project Hal" path breaks `for f in $(grep ...)` — use `while read` with process substitution instead.
- **Result:** All 12 repos updated. 26 remotes, 1 AGENTS.md, 18 other files. SSH known_hosts updated. Zero stragglers confirmed via `grep -rlP "git\.cove(?!\.local)" ~/code ~/projects`.

