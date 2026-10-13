# Tech debt: cove wheel packaging hygiene

Found 2026-10-13 while promoting PR #61's converge gating (found via live
`cove update --check` disagreeing with the venv run).

## Problem

Two packaging defects, both visible in every `cli/dist/cove_cli-*.whl`:

1. **Nested `build/lib/...` junk trees inside the wheel.** Each wheel ships the
   `scripts/sync_compose_resources.py` source repeated at every depth of
   `build/lib/build/lib/.../scripts/` — setuptools is sweeping the in-tree
   `cli/build/` artifacts into the wheel. Installing such a wheel pollutes
   site-packages with dead nested trees.
2. **Dotfile omission from bundled compose resources.** `compose/.env.example`
   is tracked, synced into `cli/cove/resources/compose/` by
   `sync_compose_resources.py`, but absent from the built wheel (0
   occurrences in the zip) — the packaging glob misses dotfiles. Effect:
   extracted runtime compose dirs never receive updates to the override-surface
   example, and wheel-vs-repo comparisons diverge by that file (the
   convergence-gating comparison in `cove/update.py` had to exclude
   `.env.example` explicitly).

## Why it matters

The wheel is the single source of truth ("reinstalling cove IS the deploy").
Anything the wheel drops silently never reaches machines — currently just the
example file, but the same glob bug would drop any future dotfile inventory
(`.dockerignore`, `.secretsignore`, etc.). The `build/lib` junk inflates wheels
and risks stale-code shadows.

## Fix shape (when picked up)

- Packaging config: ensure the compose-resources data glob matches dotfiles
  (explicit `package-data` / `include-package-data` entry for
  `resources/compose/*` including dot-prefixed names), or switch the sync step
  to emit a plain-named file the packager already includes.
- Release hygiene: remove `cli/build/` (`rm -rf cli/build`) before `uv build`
  in the promote/release flow, and prefer `uv build` from a clean tree.
- Guard: a contract test that builds the wheel and asserts (a) no member path
  starts with `build/`, and (b) `cove/resources/compose` member set equals the
  synced `cli/cove/resources/compose` tree exactly.

## Workaround today

Convergence gating ignores `.env.example` and generated files, so update
decisions stay correct despite (2). The `build/lib` junk is inert once
installed (nothing imports it) but should still be cleaned.