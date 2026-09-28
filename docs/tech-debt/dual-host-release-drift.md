# Releases must exist on both GitHub and Forgejo — today they drift

**Found:** 2026-09-28, while cutting v0.9.0 (`cove up --all`)
**Status:** Historical gap CLOSED 2026-09-28 — v0.6.0–v0.9.0 backfilled on both hosts (wheels rebuilt from tags), `scripts/release.sh` is the canonical dual-host publisher, and `.github/workflows/release.yml` (replaced goreleaser scaffold) automates the GitHub side on tag push. Residual: Forgejo-side CI not wired — the runner could publish it, but it needs a Forgejo secret + workflow (`​.forgejo/workflows/`), so the Forgejo half stays with the local script.

## Required state

Every release ships to **both** remotes, with the wheel attached:

- **GitHub** (`github` remote, `cristoslc/cove`) — the public face. The README's
  install path (`uv tool install --from https://github.com/cristoslc/cove/releases/download/...`)
  points here; anyone outside the tailnet installs from GitHub releases.
- **Forgejo** (`origin`, `git.cove`/`cristos/cove`) — the operator's primary.
  Tags land here first; the local `fj` CLI and CI integrate with it.

A release = annotated tag on `main` + release object + `cove_cli-<ver>-py3-none-any.whl`
attached + notes taken from the matching CHANGELOG section.

## Actual state (audit 2026-09-28)

| artifact | GitHub | Forgejo (git.cove) |
|---|---|---|
| tags | up to **v0.6.0** | all (through v0.9.0) |
| releases | up to **v0.5.0** | only **0.5.1** |
| wheels | ≤ 0.5.0 | 0.5.1 only |

Consequences: GitHub installs of anything ≥ 0.5.1 are impossible; Forgejo has
tags with no release objects (no notes, no wheel, no `fj release` trail); the
two histories tell different stories about what shipped.

## Why it drifted

1. **The promote flow is single-host.** AGENTS.md's promote recipe
   (sync → `uv build --wheel` → `uv tool install`) covers the local tool only;
   pushing the tag to `origin` is the last remote step. Nothing pushes to
   `github`, creates release objects, or attaches wheels. Releases that did
   exist (≤ 0.5.1) were cut by hand before the flow formalized.
2. **`.github/workflows/release.yml` is a stale goreleaser/Go scaffold** —
   triggers on `v*` tags, invokes goreleaser with `go-version: "1.22"`, but the
   repo has no `.goreleaser.yaml` and the CLI is Python. It can only fail.
   It hasn't even fired since GitHub tags stopped at v0.6.0.
3. **No single command owns "publish".** The knowledge lives in chronicles
   (`docs/chronicles/*/2026-09-25T152500-v0.7.0-promote.md`) instead of a script.

## Fix shape — SHIPPED 2026-09-28

- `scripts/release.sh <ver>` (repo root `scripts/`) — canonical dual-host
  publish: pushes the tag to `origin` + `github`, extracts the version's
  CHANGELOG section as notes, creates/uploads the GitHub release, creates the
  Forgejo release, wheel attached everywhere. Idempotent (existing releases
  are detected and skipped/filled).
- `.github/workflows/release.yml` — rewritten from the dead goreleaser
  scaffold to a uv wheel build + GitHub release on `v*` tag push (GitHub side
  only; it cannot reach the LAN-only Forgejo).
- AGENTS.md Promote section now states the both-hosts requirement and points
  at `scripts/release.sh`.
- Backfill: releases + wheels for v0.6.0, v0.7.0, v0.7.1, v0.8.0, v0.9.0 on
  both hosts (wheels rebuilt from their tags in throwaway worktrees; verified
  era-correct bundled compose). GitHub tags v0.7.0–v0.8.0 were pushed
  (they had never left git.cove); v0.9.1 re-marked `--latest` after the
  backfill briefly displaced it.
- The pre-backfill wheels in `cli/dist/` for ≤ 0.5.1 were left as historical
  artifacts; releases ≤ 0.5.x were not touched.

## Backfill provenance

Backfilled wheels are rebuilt from the tagged source (`git worktree add
--detach` → sync_compose_resources → `uv build --wheel`), not retrieved from
any prior build — dist/ held no wheels for 0.6.0+ (only a 0.6.0 sdist). Each
wheel's bundled compose was spot-checked against its era (0.6.0: no ADE; 0.9.0:
ADE core, no profile).
