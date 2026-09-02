# Plan: Preserve runtime `.env` across compose re-extraction (promote safety)

**Status:** Ready for sashay
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

1. **`cli/cove/stateless.py` — `extract_resources()`**: preserve runtime files
   across re-extraction. Define a module-level constant:
   `RUNTIME_PRESERVED_FILES = (".env",)`.
   Before `shutil.rmtree(target)`, copy each preserved file to a temp stash
   (`tempfile.mkdtemp`); after re-copy, restore into the target; clean up.
   Fail loud: if a preserved file exists but cannot be read, let the exception
   propagate (never swallow).
2. **`cli/cove/stateless.py` — blank data-root preflight (fail loud at boundary)**:
   new function `assert_no_blank_data_roots(compose_dir: Path)` that runs
   `docker compose --project-directory <dir> config` (stderr captured), raises
   `click.ClickException` if (a) the command fails, or (b) any
   `level=warning msg="The \"..._DATA_ROOT\" variable is not set` line appears.
   Call it from `cove up` (cli.py) after `ensure_init()` / `resolve_compose_dir()`,
   before any ansible run — only when `~/.config/cove/compose/.env` is absent or
   blank-rooted... **No**: keep it simple — always run the preflight on the
   *deployed* dir only when `resolve_compose_dir()` returned `_config_compose_dir()`
   (installed mode). Dev/worktree modes use a repo compose dir where `.env` is
   gitignored/dev-supplied and docker isn't necessarily live; skip there.
3. **`docs/services/forgejo.md`** — correct the promote-path section: a promote
   re-extracts the compose bundle; runtime files (`.env`) are now **preserved**
   by `extract_resources()`; the first-boot-only render still applies on a brand
   new machine.
4. **`docs/tech-debt/extract-resources-deletes-env.md`** — append "RESOLVED" note
   with PR reference (do not delete the file; keep the incident record).
5. **`CHANGELOG.md`** — Unreleased/Fixed entry.

## Tests (TDD — write first, watch fail, then implement)

`cli/tests/test_resources.py` (existing conventions: `patch Path.home`,
mocked `_bundled_compose_root`, tmp_path):

- `test_preserves_env_file_on_force_reextract`: target with `.version=old`,
  an `inventory.yml`, and a `.env` with sentinel content; force extract; assert
  `.env` survives byte-identical and `.version` updated. (RED: currently `.env`
  is deleted by rmtree.)
- `test_preserves_env_file_on_maybe_reextract`: same via `maybe_reextract()`
  path (version mismatch).
- `test_no_preserved_files_new_install`: fresh extract still works when no
  `.env` exists.
- `TestAssertNoBlankDataRoots`:
  - `test_fails_when_compose_config_warns_blank` (stub subprocess returning the
    observed warning line → ClickException).
  - `test_raises_when_compose_config_fails` (returncode != 0 → ClickException).
  - `test_passes_clean_output` (no warning → no raise).
  - `test_skipped_in_dev_mode` (function itself always checks; the *skip* logic
    lives in `cove up` — test that `up`'s guard only calls the preflight in
    installed mode via source/assert or by factoring the guard into a small
    helper `_is_installed_mode(compose_dir)` and unit-testing it).

## Non-goals

- No change to bringup.yml first-boot-only render semantics.
- No compose file changes (blank-defaults remain in compose; the preflight is
  the guard, not YAML surgery).
- No re-architecture of stateless extraction (temp-dir restore only).

## Acceptance

- New tests red→green; full gate `uv run --directory cli pytest -x -q -m "not e2e and not staging"` green.
- Manual verification on the live machine: `cove init` (or promote path) with a
  sentinel `.env` present → `.env` survives.
- Tech-debt doc marked RESOLVED; CHANGELOG updated.

## Coverage matrix rows

- `extract_resources preserves runtime .env on re-extraction` — blast high, happy/sad/edge executable, corner skip
- `cove up fails loud on blank data roots (installed mode)` — blast high, happy/sad executable, edge skip, corner skip