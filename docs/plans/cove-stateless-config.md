# Plan: Cove Stateless Config

**Date:** 2026-06-14
**Status:** Active
**Based on:**
- `docs/musings/cove-stateless-config-musing-1-state-of-world.md` — inventory
- `docs/musings/cove-stateless-config-musing-2-journeys.md` — user workflows
- `docs/musings/cove-stateless-config-musing-3-mechanism.md` — design
- `docs/musings/cove-stateless-config-musing-4-acceptance.md` — criteria
- `docs/musings/cove-stateless-config-musing-5-migration.md` — phasing

## Problem

`cove-cli` is installed via `uv tool install cove-cli` but the `compose/` directory containing all playbooks, templates, and configs is not bundled in the package. The CLI is effectively un-runnable when installed without the repo checkout.

Additionally, the repo contains PII (username, Tailscale FQDN, hostname) in tracked files, which blocks pushing to a public forge.

## Goal

1. `cove up` works on a clean macOS host with only `uv tool install cove-cli && cove up` + documented host prerequisites (Ansible, Colima, mkcert).
2. The repo is PII-clean and publishable.
3. Dev mode (`uv run --directory cli cove up` from the repo) continues to work unchanged.
4. All 50+ acceptance criteria in musing 4 pass.

## Constraints

- `compose/` is a self-contained unit with internal relative paths (Docker build contexts, Ansible role paths, inventory). Must be extracted as a whole tree.
- Ansible is a host prerequisite (not in Python package deps). The CLI must check for it and instruct the user to install.
- The repo's `compose/` is the source of truth for dev. The package's bundled `cli/cove/resources/compose/` is the source of truth for installed mode. A sync step keeps them in lockstep.
- macOS only (for now).

## Architecture

### State locations

```
~/.config/cove/                       # user state root
├── compose/                          # extracted resources (read-write at runtime)
│   ├── .version                      # cove-cli version that produced this tree
│   ├── docker-compose.yml
│   ├── bringup.yml
│   └── ... (full compose/ tree)
└── state/                            # user-customized state
    └── hosts/<hostname>.yml          # Ansible host_vars override
```

```
~/Documents/cove-data/                # runtime data (unchanged from today)
├── certs/                            # mkcert certs
├── forgejo/{gitea,git,ssh}/          # Forgejo state
├── vault/{data,logs}/                # Vault state
├── pages/sites/                      # Pages state
└── dnsmasq/cove.conf                 # rendered dnsmasq config
```

### Resource resolution priority

`cove` resolves the compose directory in this order:

1. `$COVE_COMPOSE_DIR` env var (escape hatch)
2. `<CWD>/compose/` if `inventory.yml` exists (dev mode)
3. `<CWD>/.worktrees/<CWD basename>/compose/` (worktree dev mode)
4. `<git-root>/compose/` if `inventory.yml` exists (dev mode from subdir)
5. `~/.config/cove/compose/` if it exists (installed mode, after `cove init`)
6. Otherwise: error with "Run `cove init` first"

### `cove init` semantics

- Idempotent: re-running with the same version is a no-op
- Version-aware: re-runs with `--force` re-extracts
- Self-bootstrapping: `cove up` auto-inits if needed
- Installs missing Ansible collections
- Does NOT touch `~/Documents/cove-data/` (data preserved)
- Does NOT touch `~/.config/cove/state/` (user state preserved)

### User state overlay

User-specific values (PII, Tailscale FQDN, custom admin username) live in `~/.config/cove/state/hosts/<hostname>.yml`. Ansible loads this file via `-e @<file>`, overlaying it on the shipped `group_vars/all.yml`. The user state file is created on first run with auto-detected values; the user can edit it freely.

## Phases

Each phase is a separate PR. Each phase leaves `cove up` working.

| # | Title | PR | Goal | Est. time |
|---|-------|-----|------|-----------|
| 1 | PII cleanup | pr-7 | Strip PII from `group_vars/all.yml`, add `host_vars/` template, update `.gitignore` | 30 min |
| 2 | Bundle resources | pr-8 | Copy `compose/` to `cli/cove/resources/compose/`, update `pyproject.toml` | 30 min |
| 3 | Init + resolver | pr-9 | `cove init` subcommand, new resolver, auto-init in `cove up` | 1.5 hr |
| 4 | Host vars autodetect | pr-10 | First-run `host_vars/<hostname>.yml` creation with auto-detected values | 1 hr |
| 5 | Version re-extract | pr-11 | Version mismatch auto-re-extract | 30 min |

**Total: ~4 hours.**

## Phase 1 — PII cleanup

### Changes

1. **`compose/group_vars/all.yml`**: remove `admin_username`, `admin_email`, `repo_owner`, `repo_name` defaults. Add comments explaining they come from `host_vars/<hostname>.yml`. Set `ts_dns_name` default to `localhost`.

2. **`compose/host_vars/localhost.yml.example`** (NEW): template with PII values as comments / placeholders. The actual `host_vars/<hostname>.yml` is gitignored.

3. **`.gitignore`**: add `compose/host_vars/*.yml` (keep `.example` tracked).

4. **`bringup.yml`**: preflight check that errors if `admin_username` is empty when needed. (Today the playbook uses `admin_username` in the email template; if empty, the email is `forgejo@`. That's a tolerable default but worth flagging.)

5. **Tests**: add a pytest that grep's the repo for PII patterns and fails if any are found in non-doc files.

### Acceptance

- `git grep -nE "(cristos|lc\.cristos@gmail\.com)" -- ':!docs/'` returns zero hits
- `git grep "taila90e7.ts.net"` returns zero hits
- `git grep "MBPBK-202602"` returns zero hits
- `cove up` from the repo still works (using a local gitignored `host_vars/MBPBK-202602.yml`)

## Phase 2 — Bundle resources

### Changes

1. **`cli/cove/resources/compose/`** (NEW): copy of `compose/` tree, excluding rendered files
2. **`cli/cove/resources/compose/.gitignore`** (NEW): excludes rendered files (defense in depth)
3. **`cli/scripts/sync_compose_resources.py`** (NEW): copies `compose/` → `cli/cove/resources/compose/`, excluding rendered files. Run as part of pre-commit or `uv build`.
4. **`pyproject.toml`**: add `"cove.resources" = ["**/*"]` to package-data

### Acceptance

- `diff -r compose/ cli/cove/resources/compose/ --exclude="*.env" --exclude="default.conf" --exclude="cove.conf"` returns zero
- `uv build` produces a wheel containing the resources
- `uv tool install .` then `python -c "from importlib.resources import files; list(files('cove.resources.compose').iterdir())"` lists the compose tree

## Phase 3 — Init + resolver

### Changes

1. **`cli/cove/resources.py`** (NEW): `resolve_compose_dir()`, `extract_resources()`, `ensure_init()` functions
2. **`cli/cove/cli.py`**: add `init` subcommand, update `_find_compose_dir()` (or replace) to use new resolver
3. **`cli/cove/cli.py`**: `cove up` auto-inits if needed
4. **Tests** for resolver, extraction, idempotency

### Acceptance

- `cove init` extracts resources to `~/.config/cove/compose/`
- `cove init` is idempotent (re-run with same version is no-op)
- `cove init --force` re-extracts
- `cove up` from `/tmp` works (no compose/ in CWD)
- `cove up` from repo still works (dev mode)
- All 66+ existing tests pass; new tests pass

## Phase 4 — Host vars auto-detection

### Changes

1. **`cli/cove/state.py`** (NEW): `ensure_host_vars()` function
2. **`cli/cove/cli.py`**: `cove up` creates `~/.config/cove/state/hosts/<hostname>.yml` on first run
3. **Auto-detection** for: `admin_username` (from `$USER`), `admin_email` (from git config or env), `op_vault` (from `OP_VAULT` env or default "Private"), `ts_dns_name` (from `tailscale status --json` or default "localhost")
4. **Env var overrides**: `COVE_ADMIN_USERNAME`, `COVE_ADMIN_EMAIL`, `COVE_OP_VAULT`, `COVE_TS_DNS_NAME` skip auto-detection

### Acceptance

- On a clean `~/.config/cove/`, `cove up` creates the host_vars file
- The file contains the correct auto-detected values
- Editing the file and re-running `cove up` uses the new values
- Env var overrides work

## Phase 5 — Version re-extraction

### Changes

1. **`cli/cove/resources.py`**: `maybe_reextract()` function
2. **`cli/cove/cli.py`**: `cove up` checks version, calls `maybe_reextract` if mismatch
3. **Flags**: `cove up --no-upgrade` (skip re-extract), `cove init --purge` (remove extracted tree)

### Acceptance

- Version mismatch triggers re-extract
- User state preserved
- User data preserved
- `--no-upgrade` skips re-extract
- `--purge` removes extracted tree

## Verification (final gate)

After all phases:

1. `uv run --directory cli pytest cli/tests/` — all tests pass
2. `cove down` — cleans up current state
3. `uv tool install .` — installs the new version
4. `rm -rf ~/.config/cove/`
5. `cd /tmp && cove up` — brings up cove from a fresh install with no repo
6. `curl -k https://git.cove/api/healthz` — returns 200
7. `curl -k https://vault.cove/v1/sys/health` — returns 200 (or 472 if not unsealed)
8. `cove creds vault-get ...` — works
9. `cove down && cove up` — idempotent
10. `git grep -nE "(cristos|taila90e7|MBPBK)" -- ':!docs/'` — zero hits

If all 10 pass, the migration is done.

## Rollback

If the migration needs to be reverted:
- `git revert` all PRs
- `uv tool install .` to get the previous version
- `rm -rf ~/.config/cove/` to clean up new state
- The repo's `compose/` is unchanged, so the old way works

## Out of scope (deferred)

- Multi-version cove-cli side-by-side
- Schema migration of user data on cove-cli upgrades
- Linux/Windows support
- Encrypted user state
- Hot-reload of `group_vars` changes
- Custom install location (`$XDG_CONFIG_HOME` support)
- Cross-host data sync (rsync helpers)

These are documented in the musings as future work.

## Open questions

- Should the Tailscale FQDN be prompted for, or always auto-detected? Auto-detect is the answer (it's available via `tailscale status --json`).
- Should the user be able to skip sudo elevation? Yes, via `--no-sudo`.
- Should `cove init` ever prompt for values? Only if a value can't be auto-detected AND there's no env var override. For macOS first-time setup, everything can be auto-detected.
