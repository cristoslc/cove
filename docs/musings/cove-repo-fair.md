# What "Fair" Looks Like for the Cove Repo

**Status:** Musing — structural question about the repo boundary.

## The tension

Cove's identity is *one install, one command, one working platform.* The CLI is the user's interface to Cove. But the repo has two top-level concerns that look like peers: `cli/` and `compose/`. A new contributor sees a Python package and an infrastructure directory and has to figure out how they relate.

The CLI already bundles compose as package data (`cli/cove/resources/compose/`). `cove init` extracts it to `~/.config/cove/compose/`. The top-level `compose/` is the development source of truth, and the bundled copy is a manually-maintained mirror that's drifted out of sync.

This is the cruft that matters. Not `.claude/` or `bin/` — those are noise. The structural cruft is the duplication.

## What "fair" means

Fair means the repo structure matches the user's mental model. The user installs `cove`, runs `cove up`, and gets a harbor. They should never need to know that `compose/` exists. The repo should reflect that.

Fair also means the developer's workflow is honest. If compose is developed in one place and shipped from another, the build process should own the copy — not the developer's memory.

## Options

### A. Compose stays at top level, CLI references it at runtime

The CLI resolves compose via `resolve_compose_dir()`: `$COVE_COMPOSE_DIR`, `./compose`, git-toplevel `compose/`, `~/.config/cove/compose/`. During development, the developer works in `compose/` and the CLI finds it automatically.

This is the current state, minus the bundled copy. The bundled `cli/cove/resources/compose/` gets removed. `cove init` copies from the git-toplevel `compose/` instead of from package data.

**Pros:** Single source of truth. No drift. Developer edits `compose/`, CLI picks it up immediately.

**Cons:** The CLI depends on the repo layout at runtime during development. `cove up` from an installed wheel needs `cove init` to have run first. The repo still has two top-level concerns.

### B. Compose moves into the CLI package, top-level compose/ becomes a dev symlink

The canonical compose lives at `cli/cove/resources/compose/`. The top-level `compose/` is a symlink: `compose -> cli/cove/resources/compose/`. During development, the symlink makes it discoverable by `resolve_compose_dir()`. The wheel bundles the real directory.

**Pros:** Single source of truth. The wheel is self-contained. The symlink is transparent to the developer.

**Cons:** Symlinks in git are awkward (git tracks the symlink, not the target). `git checkout` on a system without the symlink target gets a broken link. Some tools (Docker build context, CI) may not follow symlinks.

### C. Compose moves into the CLI package, top-level compose/ is removed

The canonical compose lives at `cli/cove/resources/compose/`. During development, the developer runs `cove up` from the repo root and `resolve_compose_dir()` finds it via the git-toplevel fallback (it checks `git_root / "compose"`). But `compose/` no longer exists at the git root — so the fallback fails.

Fix: update `resolve_compose_dir()` to also check `git_root / "cli" / "cove" / "resources" / "compose"`, or add a `COVE_COMPOSE_DIR` env var to the dev workflow.

**Pros:** Cleanest top level. The repo says "this is a Python project" unambiguously.

**Cons:** The dev workflow needs an env var or a config change. Slightly more ceremony for the developer.

### D. Compose stays at top level, the build copies it into the wheel

The canonical compose lives at `compose/`. The build process (setuptools `MANIFEST.in` or a custom build hook) copies `compose/` into `cli/cove/resources/compose/` before building the wheel. The bundled copy is a build artifact, never committed.

**Pros:** Single source of truth committed. No drift. The wheel is self-contained. The developer edits `compose/`, the build handles the rest.

**Cons:** The build step is invisible — if you forget to rebuild, the wheel is stale. CI catches this, but local dev might not. Adds a build dependency (copy step).

### E. Compose stays at top level, the CLI reads it from the filesystem at runtime

The CLI never bundles compose. `cove init` copies from a well-known path (git-toplevel `compose/` during dev, or the wheel's `cove.resources` during install). The wheel includes compose as package data, but the development workflow uses the git-toplevel copy directly.

This is essentially option A, which is the current state minus the bundled copy. The question is whether to keep the bundled copy at all.

## The real question

The bundled copy exists so that `pip install cove-cli` gives you a working `cove up` without needing the git repo. That's the right behavior for an end user. The question is how to maintain it without drift.

Option D (build copies it) is the most honest: compose is developed in one place, the build artifact is ephemeral. But it requires a build step that's easy to forget.

Option B (symlink) is the simplest: one canonical location, the symlink is transparent. But git symlinks have edge cases.

Option A (no bundled copy, CLI finds compose at runtime) is the simplest of all, but it means the wheel is incomplete — `cove init` needs the git repo or a prior `cove init`.

## What I think

Option D, with a `Makefile` or `scripts/build.sh` that handles the copy before `pip install -e .` and before `uv build`. The copy step is:

```bash
rm -rf cli/cove/resources/compose
cp -r compose cli/cove/resources/compose
```

Add it to `pyproject.toml` as a `tool.setuptools.build-hook` or a `MANIFEST.in` directive. Make it part of the CI pipeline. The developer never thinks about it — `uv build` or `pip install` triggers it automatically.

The top-level `compose/` stays. The bundled copy is a build artifact, gitignored. The `.gitignore` already has `compose/nginx/default.conf` — extend it to cover the whole `cli/cove/resources/compose/` directory.

## What this means for the rest

- `seeds/` at top level (one file) moves into `compose/seeds/` — it's infrastructure, not a separate concern.
- `scripts/staging/` stays or moves to `.github/` — it's Cove's own CI, not user-facing.
- `.claude/`, `.goose/`, `bin/` — remove from tracking, add to `.gitignore`. Personal agent configs don't belong in a public repo.
- `AGENTS.md` / `CLAUDE.md` — keep if useful for OpenCode-using contributors, or strip for a clean open-source surface.

The result: the top level says "this is a Python project with infrastructure-as-code" — `cli/`, `compose/`, `docs/`, `.github/`. The wheel says "this is a self-contained tool." The build process owns the bridge between them.
