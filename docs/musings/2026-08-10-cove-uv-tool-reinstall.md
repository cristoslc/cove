# Musing: how to ship the `cove` CLI (uv tool reinstall, staging, rollback)

Date: 2026-08-10. Context: a jam session fixing `cove up`'s missing docker CLI bootstrap. That surfaced a real gap in how we promote CLI changes to the machine.

## What we discovered (map of the artifact flow)

There are **three** copies of `bringup.yml` and they are NOT all equal:

1. `compose/` at repo root — **canonical source**, tracked in git. This is the real single source of truth.
2. `cli/cove/resources/compose/` — a **build-time snapshot** of `compose/`, synced by `cli/scripts/sync_compose_resources.py` (`compose/` → resources, excluding `.env`, `default.conf`, `host_vars/*.yml`, PII seeds). Run by `setup.py`'s `BuildPyWithSync` during `uv build`.
3. `~/.config/cove/compose/` — the **deployed runtime copy**, extracted by `cove.init`/`ensure_init`/`maybe_reextract`. It is regenerated whenever the bundled content hash changes (`.version`).

**The bug in this session:** I edited #3 (and then #2), but the canonical source #1 was untouched. `resolve_compose_dir` prefers cwd/`compose`, then git-root `compose`, then `~/.config/cove/compose` — so when running from inside the repo, the deployed wheel's bundled resources don't even matter. Any agent must edit **`compose/` at repo root**, not the extracted copy. This is a classic "edited the wrong copy" trap that the reinstall instructions must guard against.

## The actual problem: promoting CLI changes

The `cove` CLI is a uv tool installed from a wheel built out of `cli/`:

- stable/shipped tool: `~/.local/bin/cove` (uv tool `cove-cli`), from `cli/dist/cove_cli-<ver>.whl`
- dev/test loop: `uv run --directory cli cove ...` (project-local, no reinstall)

To **promote** a change you must: `uv build --wheel` (syncs resources) → `uv tool install --force --from cli/dist` (or the wheel path). Nothing automates this today; it's manual tribal knowledge.

## Design tension worth weighing

Two ways to make `cove` usable during a sashay without clobbering the stable tool:

**Option A — keep `cove` stable; dev via `uv run --directory cli`.**
Reinstall `cove` only after tests pass and the branch is merged to main. Clean separation: the deployed tool is always the last good release; `uv run` is the dev surface. Reinstall is a release-time action, not a per-edit action. Rollback = `uv tool install --force --from` the last tag's wheel (or `git checkout <tag>` the repo-root compose + rebuild).

**Option B — a `cove-staging` (or `cove-dev`) tool.**
A second uv tool that points at the current worktree/branch resources, so you can test branch behavior without ever touching stable `cove`. Pros: you can exercise branch CLI + resources side-by-side with stable. Cons: more moving parts, two tools to keep straight, and (per discovery above) `resolve_compose_dir` already prefers the in-repo `compose/` anyway — so when working inside a checkout you ALREADY get branch resources via `uv run` without a second tool.

**Lean:** Option A. The `cove-staging` tool is mostly redundant given `resolve_compose_dir` prefers the repo-local `compose/`. A dedicated staging tool earns its place only if we need to test a *built wheel's* resources against the live stack (tier-2 `staging` tests) — and `conftest.py` already builds a wheel into an isolated venv for exactly that. So we get staging coverage from the test harness, not from a second permanent tool.

## What to codify (AGENTS.md addition)

Add to project AGENTS.md a **"Reinstall the cove CLI (uv tool)"** section:
- Canonical source is `compose/` at repo root — edit that, never `~/.config/cove/compose/`.
- Test command before promote: `uv run --directory cli pytest -x -q -m "not e2e and not staging"`.
- Promote (only after tests green AND merge to main): `uv build --wheel` then `uv tool install --force --from <wheel>`.
- Rollback on breakage: reinstall the wheel for the last tag, i.e. `git checkout v<last-tag> -- cli/ compose/` (or rebuild from the tag), then re-run the promote step.
- Sashay-aware: the promote step is **not** a sashay trunk action — it's post-merge release. During a sashay, test with `uv run --directory cli` and never reinstall the stable tool from a branch wheel.

## Next step

If this crystallizes, the concrete work is: write the AGENTS.md section (Option A), and fix the session's real bug by editing `compose/bringup.yml` at repo root (canonical) so the docker bootstrap actually ships. That's a sashay candidate.
