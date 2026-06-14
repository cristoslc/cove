# Musing 5 — Migration Plan

OK, the design is in musing 3, the criteria are in musing 4. Now: the order of operations. How do I get from here to there without breaking anything mid-flight?

## The constraint: don't break what works

The current `cove up` (using the repo) works. It's in active use. If I break it, I lose my own platform mid-migration. So every step must leave the system in a runnable state.

## Phases

I'm going to break the migration into 5 phases. Each phase is independently shippable. Each phase has its own PR. After each phase, `cove up` still works.

### Phase 0 — Inventory and prep (no code change)

**Goal:** confirm the inventory in musing 1, find any surprises.

**Tasks:**
- Read all 5 playbooks, all group_vars, all host_vars, all templates
- Verify the .gitignore covers all rendered files
- Check the `__pycache__/` situation
- Verify `cove up` works TODAY (baseline)

**Acceptance:** I have a working `cove up` and a complete picture of what files exist.

**Risk:** none.

### Phase 1 — Move `group_vars/all.yml` to PII-free defaults + add `host_vars` mechanism

**Goal:** the repo's `compose/` is PII-clean. The PII moves to a per-host file (which is gitignored).

**Tasks:**
- Edit `compose/group_vars/all.yml`:
  - `admin_username: ""` (or remove)
  - `admin_email: ""` (or remove)
  - `ts_dns_name: "localhost"` (already this, but verify)
  - Add comments explaining where PII values come from
- Create `compose/host_vars/localhost.yml.example` with the PII template values
- Add `compose/host_vars/<hostname>.yml` to `.gitignore`
- Verify the bringup playbook still works (PII defaults are empty, but the user can supply via host_vars)
- Add a `cove up` preflight that reads the hostname, checks for `host_vars/<hostname>.yml`, errors clearly if missing critical values

**Acceptance:**
- `git grep` for PII patterns in tracked files returns zero hits (musings/plans excluded)
- `cove up` from the repo still works (using a temporary host_vars file)
- The repo is publishable

**Risk:** moderate. If the bringup playbook breaks because of empty defaults, I need to fix it. Mitigation: have a local `compose/host_vars/MBPBK-202602.yml` (gitignored) that provides the values during testing.

**Why first:** the PII cleanup is independent of the stateless migration. Doing it first means the rest of the migration doesn't compound PII issues.

### Phase 2 — Bundle `compose/` as a package resource

**Goal:** the `cove-cli` package contains the compose tree.

**Tasks:**
- Create `cli/cove/resources/compose/` directory
- Add `cli/scripts/sync_compose_resources.py` (or `make sync-resources`) that copies `compose/` → `cli/cove/resources/compose/`, excluding rendered files
- Add `[tool.setuptools.package-data]` entry for `"cove.resources" = ["**/*"]` in `pyproject.toml`
- Add a `.gitignore` in `cli/cove/resources/compose/` that excludes the same rendered files
- Run `uv build` and verify the wheel contains the resources
- Run `uv tool install .` and verify `from importlib.resources import files; files("cove.resources.compose")` works

**Acceptance:**
- `diff -r compose/ cli/cove/resources/compose/` (excluding rendered files) returns zero differences
- The built wheel contains all the expected files
- The installed package can be introspected via importlib.resources

**Risk:** low. The repo's `compose/` is still the source of truth; the package resource is a build artifact.

**Why second:** the bundling is mechanical. It doesn't change runtime behavior. The CLI still uses `_find_compose_dir()` and finds the repo. No user-visible change.

### Phase 3 — Add `cove init` and the resolver

**Goal:** the CLI can extract resources to `~/.config/cove/compose/` and find them on subsequent runs.

**Tasks:**
- Add `cove init` subcommand (idempotent, version-checked, force-re-extracts)
- Add `cove/resources.py` module with the extraction logic and the resolver
- Update `_find_compose_dir()` (or replace it) to use the new resolver
- Update `cove up` to auto-init if `~/.config/cove/compose/` is missing
- Update `cove down`, `cove uninstall` to use the new resolver
- Add tests for the resolver, extraction, version comparison

**Acceptance:**
- `cove init` extracts the resources correctly
- `cove up` works from `/tmp` (no compose/ in CWD, no git repo) using the extracted resources
- `cove up` from the repo still works (dev mode)
- `cove up --no-sudo` etc. still work
- All existing tests pass
- New tests pass

**Risk:** high. This is the first time the CLI has two modes. The resolver must get the priority right. Mitigation: ship the resolver behind a feature flag for one PR cycle, then remove the flag.

**Why third:** the init + resolver is the heart of the migration. After this phase, the installed mode works.

### Phase 4 — Add first-run host_vars creation

**Goal:** `cove up` works on a fresh host with no manual `host_vars/<hostname>.yml` setup.

**Tasks:**
- Add `cove/state.py` module with host_vars auto-detection
- Update `cove up` to create `~/.config/cove/state/hosts/<hostname>.yml` on first run if missing
- Add prompts (or environment variable overrides) for values that can't be auto-detected
- Update `cove init` to also create the host_vars file

**Acceptance:**
- On a clean `~/.config/cove/`, `cove up` succeeds without manual host_vars creation
- The created host_vars file contains the correct auto-detected values
- The user can edit the file post-creation and re-run `cove up` to use the new values

**Risk:** medium. Auto-detection is finicky. If `admin_email` detection fails on some hosts, the user gets a prompt they didn't want. Mitigation: env var overrides (`COVE_ADMIN_USERNAME`, etc.) skip the prompt.

**Why fourth:** without this, installed mode is annoying. The user has to manually create the host_vars file. With it, installed mode is "just works."

### Phase 5 — Re-extraction on version mismatch

**Goal:** `uv tool upgrade cove-cli && cove up` re-extracts automatically.

**Tasks:**
- Update `cove up` to compare its `__version__` against `~/.config/cove/compose/.version`
- If different, run `cove init` (which is idempotent and handles the re-extract)
- Add a `--no-upgrade` flag to skip the re-extraction (escape hatch)
- Add a `--purge` flag to `cove init` to remove the extracted tree (for clean re-init)

**Acceptance:**
- Version mismatch triggers re-extraction
- User state (`~/.config/cove/state/`) is preserved
- User data (`~/Documents/cove-data/`) is preserved
- The `--no-upgrade` flag works (for testing or pinning)

**Risk:** low. The re-extraction is a copy operation; if it fails, the previous tree is still there (because we copy to a temp dir first, then atomic rename).

**Why fifth:** the version-mismatch logic is a thin wrapper over `cove init`. Doing it after init means init is solid first.

## Order of work

I'll do phases 1, 2, 3, 4, 5 as separate PRs. Each PR is reviewable independently. Each PR keeps `cove up` working.

| Phase | PR | What | Time est. |
|-------|----|----|-----------|
| 1 | `pr-7-pii-cleanup` | Strip PII from `group_vars/all.yml`, add `host_vars/` template | 30 min |
| 2 | `pr-8-bundle-resources` | Copy `compose/` to `cli/cove/resources/compose/`, update `pyproject.toml` | 30 min |
| 3 | `pr-9-init-and-resolver` | `cove init` subcommand, new resolver, `cove up` auto-inits | 1.5 hr |
| 4 | `pr-10-host-vars-autodetect` | First-run host_vars creation, env var overrides | 1 hr |
| 5 | `pr-11-version-re-extract` | Version mismatch auto-re-extract | 30 min |

Total: ~4 hours. Doable overnight.

## What about backwards compatibility?

The current installed `cove-cli` is broken (errors out on `cove up` because no compose/). So there's nothing to be backwards-compatible with. The migration is a hard cut.

For users with an in-progress `cove up` from the old code: there are none. Single-developer tool.

For me: each PR leaves `cove up` working (either via the new code or via the repo). So I can develop and test in the repo between PRs.

## Escape hatches

If something goes wrong mid-migration:

1. **Revert the PR.** git revert, push, re-install.
2. **Use the repo directly.** `uv run --directory cli cove up` from the repo checkout always works (until phase 3 changes the resolver).
3. **`COVE_COMPOSE_DIR=/path/to/old/way cove up`** — the env var override lets me point at any compose tree.
4. **`cove init --purge && cove init`** — nuke and re-extract from scratch.

## Rollback

If the whole migration needs to be rolled back:
- `git revert` of all PRs
- `uv tool install .` to get the old version
- `rm -rf ~/.config/cove/` to remove the new state
- The repo's `compose/` is unchanged, so the old way works

## Validation strategy

After each phase, I run:
1. `uv run --directory cli pytest cli/tests/` — all unit tests pass
2. `cove up` from the repo — still works (or works via the new mechanism)
3. `cove up` from `/tmp` — works (after phase 3)
4. `cove down && cove up` — idempotency

The "verify by bringing cove up using it" is the final gate. Until that passes, the migration isn't done.

## What's NOT in this migration

Things I considered and rejected:

- **Multi-version cove-cli side-by-side** (e.g., `cove-stable` vs `cove-dev`). Defer.
- **Schema migration of user data** when cove-cli changes in incompatible ways. Defer.
- **Linux/Windows support.** Defer — macOS only.
- **Encrypted user state.** The `host_vars/<hostname>.yml` is plaintext. It contains PII (Tailscale FQDN, etc.). For a single-user local dev tool, this is fine. If we ever need to share state across users or hosts, encryption is a separate concern.
- **Hot-reload of `group_vars` changes.** `cove up` always re-runs the playbook. No hot-reload needed.
- **Custom install location.** `~/.config/cove/` is hardcoded. We could respect `$XDG_CONFIG_HOME` later. For now: hardcoded.
- **Disabling the rendered .env regeneration.** The .env is always regenerated from defaults + host_vars. The user can override vars in host_vars, but not preserve manual edits to the .env.

## When do I declare the migration done?

When all 50+ acceptance criteria in musing 4 pass, AND `cove up` works end-to-end on the installed mode (from `/tmp` or similar, with no repo). That's the gate. Everything else is supporting work.

## One more thing: the "what if I'm wrong" question

This whole design is a hypothesis. The way to test it cheaply: implement phase 1, 2, 3, then run `cove up` from `/tmp` and see if it works. If yes, the hypothesis holds. If no, the design needs revision — but the phases are independent enough that I can revise phase 3 without redoing 1 and 2.

Specifically: phase 1 (PII cleanup) is just file edits. Phase 2 (bundling) is just a copy + manifest. Phase 3 (init + resolver) is where the design could go wrong. If phase 3 is wrong, I revert that PR and try again with a different design (e.g., keep `_find_compose_dir` and just add init to populate it; OR add a "cove-home" env var the user sets manually).

OK that's the plan. Now: write the formal plan file, kick off the first PR, and start working.
