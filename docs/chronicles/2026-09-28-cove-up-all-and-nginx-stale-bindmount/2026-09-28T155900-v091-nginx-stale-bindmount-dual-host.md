---
type: final
timestamp: 2026-09-28T155900
responding-to: operator report — `cove up` died at the "Reload nginx" handler (ENOENT on default.conf)
---

## Final — v0.9.1 promoted (nginx stale bind-mount fixed; dual-host releases established)

**Incident:** `cove up` failed at the handler flush: `nginx -s reload` inside
cove-nginx died with `open() "/etc/nginx/conf.d/default.conf" failed (2: No
such file or directory)`. Root cause: bringup's `template` render of
`default.conf` is atomic (rename → new inode), but on macOS/Colima a file
bind-mount pins the inode at container creation. The running container's mount
went stale (link-count 0, `open()` → ENOENT — visible via `docker exec … ls
-la`). nginx kept serving on its in-memory config for ~70 minutes; only
reload/test (which re-open files) failed. Same family as
`docker-bindmount-auto-directory.md`, new failure mode: stale-after-rename.

**Fixes shipped in 0.9.1:**

- The `Reload nginx` handler restarts the container (bind re-resolves by
  path, ~1s blip) instead of exec-reloading. Bringup structure test pins the
  contract (`nginx -s reload` must never return).
- Live-stack remediation: `docker restart cove-nginx` — link-count 1, `nginx
  -t` green, ingress serving again.

**Dual-host releases (closes `dual-host-release-drift.md`):** audit showed
GitHub releases ≤ v0.5.0 / tags ≤ v0.6.0 while git.cove held all tags and one
release (0.5.1). Shipped: `scripts/release.sh <ver>` (canonical both-hosts
publisher, idempotent), `.github/workflows/release.yml` rewritten from the
goreleaser scaffold to a uv wheel build + GitHub release, AGENTS.md Promote
section now mandates both hosts. Backfilled v0.6.0–v0.9.0 on both hosts with
wheels rebuilt from tags in throwaway worktrees (spot-checked era-correct:
0.6.0 has no ADE; 0.9.0 has ADE core). GitHub tags v0.7.0–v0.8.0 pushed for
the first time; v0.9.1 re-marked `--latest` after the backfill displaced it.

- Gate: **625 passed / 28 deselected** (adds the handler structure test).
- Release commit `01d1893`; annotated tag `v0.9.1`; pushed to BOTH remotes;
  `gh release create` + `fj release create` with wheel and CHANGELOG notes —
  the first fully dual-host release, then the backfill followed the same path.

**Operator side, pending:** re-run `cove up` (become password theirs). Vault
was sealed after the morning restart; the failed run died before
`bootstrap_vault.yml`. Expected: bringup converges (`Up-to-date:` on nginx
config — no notify, the new restart handler's first live-fire still awaits a
real config change), Vault unseals, `cove status` 14/14.
