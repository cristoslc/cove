---
type: documentation-site
name: Forgejo Repository Mirrors docs
url: https://forgejo.org/docs/latest/user/repo-mirror/
fetched: 2026-06-04
---

# Forgejo Repository Mirrors — Official Docs

Forgejo supports built-in push and pull mirroring for branches, tags, and commits only. No issue or PR metadata is synced.

## Pull Mirror (Remote → Forgejo)

- Set up during repository creation via "New Migration" → check "This repository will be a mirror"
- Periodically syncs from remote to Forgejo
- Cannot be converted from an existing non-mirror repository
- **No issue/PR sync**

## Push Mirror (Forgejo → Remote)

- Set up in repository Settings → Repository → Mirror Settings
- Force-pushes to remote (overwrites changes)
- Supports branch filtering (comma-separated names, glob patterns)
- Can trigger "Sync when new commits are pushed"
- **No issue/PR metadata sync**

## SSH Authentication

Forgejo supports SSH as an authentication method for push mirrors. Generates an Ed25519 SSH key pair automatically.

## Branch Filter

- No filter = `git push --mirror` (all branches)
- With filter: pushes only matching branches supporting glob patterns (e.g., `feature/*`)
- **No issue/PR metadata sync at all**

## Key Limitation

Forgejo's built-in mirroring is **Git-level only** — branches, tags, and commits. There is no built-in mechanism to sync issues, PRs, labels, milestones, or any other repository metadata.