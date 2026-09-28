# Releases must exist on both GitHub and Forgejo — today they drift

**Found:** 2026-09-28, while cutting v0.9.0 (`cove up --all`)
**Status:** Open — v0.9.1 released manually on both hosts as a stopgap; automation still missing.

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

## Fix shape

- Replace `release.yml` (or add `cli/scripts/release.py`): on a tag push —
  build the wheel, create the GitHub release **and** the Forgejo release with
  the wheel attached, notes extracted from the tag's CHANGELOG section
  (`gh release create --notes` / `fj release create --asset`).
- Push tags to both remotes in one step (origin + github).
- Backfill the drift: at minimum release objects + wheels for v0.6.0+ on both
  hosts (rebuild wheels from tags; dist/ already holds a few).
- Record the dual-host requirement in AGENTS.md's promote section so the next
  manual release cannot forget a host.

## Stopgap applied for v0.9.1

Manual dual-host release: tag pushed to both remotes, `gh release create` +
`fj release create` with `cli/dist/cove_cli-<ver>-py3-none-any.whl` attached
and the 0.9.1 CHANGELOG section as notes. Later releases should reuse — then
retire — this manual path.
