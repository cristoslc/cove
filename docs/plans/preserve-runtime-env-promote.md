---
title: Preserve runtime Compose files across resource extraction
status: in progress
updated: 2026-10-17
tags: [compose, preservation, sashay]
---

# Plan: Preserve runtime Compose files across resource extraction

**Source:** Tech debt log `docs/tech-debt/extract-resources-deletes-env.md` (incident during PR #46 promote, 2026-09-02)
**Type:** Bug fix / hardening — chore sashay

## Problem (observed live)

`extract_resources()` (`cli/cove/stateless.py`) `rmtree`s the deployed compose dir
whenever the bundle hash changes. A promote therefore **deletes the runtime
`.env`**. A subsequent bare `docker compose up -d forgejo` runs with blank
`FORGEJO_DATA_ROOT`, bind-mounts a fresh empty path, and Forgejo boots with an
empty database — silently. Recovery required a manual `.env` rebuild; real data
was never lost (host `~/Documents/cove-data/forgejo/` intact), but the failure
mode is silent and the docs assume `.env` survives promotes.

## Change

1. **`cli/cove/stateless.py` — in-place resource refresh**: preserve the narrow runtime allowlist `(".env", "nginx/default.conf")` in place while replacing bundled resources. Prune stale non-allowlisted entries, retaining the ancestor directory for `nginx/default.conf`, then copy fresh bundle resources while skipping those exact paths. Safely invalidate `.version` before pruning and write a new marker only after all bundled copies succeed; then a partial copy failure forces the next `ensure_init()` to retry without removing the last runtime files.
2. **Safe path handling**: validate `.env`, `nginx/default.conf`, and the `.version` marker using descriptor-relative `O_NOFOLLOW` opens and require regular files. Use `O_NONBLOCK` to reject FIFOs without hanging. Walk from the resolved home directory without following symlinked Compose parents. Restrict `.env` to owner-only permissions without replacing its inode, unlink `.version` safely before pruning, and write it atomically only after copying succeeds.
3. **Test isolation**: redirect `TestCoveUpCommand` and `TestNoUpgradeFlag` resource initialization to temporary homes and patch resource extraction entry points, so the required gate cannot alter the operator's installed Compose tree.
4. **Docs and release notes**: clarify that bundled sources/pins refresh while `.env` and generated nginx config remain in place until `cove up` rerenders nginx. Update the Unreleased changelog and coverage matrix. Keep the incident record open until merge.

### Deferred separately

The earlier plan proposed a `docker compose config` blank-data-root preflight. That guard is not required to preserve an existing `.env`, and a guard before first-boot env rendering needs separate lifecycle design and tests. Do not include it in this preservation change.

## Tests (TDD — write first, watch fail, then implement)

`cli/tests/test_resources.py` uses temporary roots and a mocked bundled resource directory:

- Exercise forced and hash-mismatch extraction; assert `.env` and generated nginx bytes, private mode, and inode identity remain stable while bundled pins and templates refresh.
- Inject a resource-copy failure after partial copying; assert both runtime files remain and `.version` is absent, allowing the next `ensure_init()` to retry.
- Reject symlinked runtime files, symlinked Compose/runtime parents, and FIFOs without blocking.
- Verify `.env` permissions are restricted without replacing its inode.
- Keep new-install extraction functional when runtime files do not exist.

`cli/tests/test_cli.py` isolates `TestCoveUpCommand` and `TestNoUpgradeFlag` from the actual installed resource directory. Confirm its manifest is unchanged before and after the required gate once parent recovery is complete.

## Non-goals

- No live service or staging operations, release, or stable tool install.
- No changes to bringup.yml first-boot env rendering.
- No preservation of bundled Compose source, pins, or arbitrary activation backups.
- No blank-root preflight in this change.

## Runtime preservation refinement (2026-10-17)

The implementation keeps the two allowlisted runtime files physically in place
while pruning stale bundled resources around them. This replaces the original
temp-stash design: copy failure cannot discard the last runtime copy, and nginx
keeps the same bind-mounted inode until `cove up` rerenders it. Other bundled
Compose source and pins are refreshed on each successful extraction.

## Acceptance

- The focused regression and isolation tests pass in temporary roots.
- The required gate `uv run --directory cli pytest -x -q -m "not e2e and not staging"` passes after parent recovery is paused and the live installed-directory manifest is recorded before/after.
- The local chronicle is committed and projected as separate PR comments.
- The draft PR remains unmerged; no live mutation or release occurs in this work.

## Coverage matrix rows

- `Compose resource re-extraction preserves persistent .env and nginx config inodes, including copy failure, and validates its version marker` — blast high, happy/sad/edge executable, corner skip