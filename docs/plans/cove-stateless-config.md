# Plan: Cove Stateless Config

**Date:** 2026-06-14
**Based on:** `docs/musings/cove-stateless-config.md`

**Problem:** Cove is installed via `uv tool install cove-cli` but its playbooks, compose files, and templates are referenced by relative path from the repo checkout. Hardcoded config files contain PII (username, Tailscale FQDN) that must be scrubbed before pushing to GitHub. The repo should contain only templates and Python resources — no rendered config, no machine state.

**Constraint:** The `compose/` directory is a self-contained unit with internal relative paths. `docker-compose.yml` references `./nginx/`, `./dnsmasq/` (build context + Dockerfile), `./vault/vault.hcl` by relative path. Ansible playbooks reference `roles/`, `group_vars/`, `inventory.yml` relative to themselves. The entire tree must be extracted as a unit, not file-by-file.

## Changes

### 1. Bundle `compose/` as a Python package resource

The entire `compose/` directory tree becomes a package resource at `cli/cove/resources/compose/`. This preserves all internal relative paths. The resource is extracted to `~/.config/cove/compose/` on first run.

```
cli/cove/resources/compose/
├── docker-compose.yml
├── .env.example
├── inventory.yml
├── group_vars/
│   └── all.yml
├── roles/
│   └── os_keystore/
│       └── tasks/
│           ├── main.yml
│           ├── preflight.yml
│           ├── get.yml
│           └── store.yml
├── nginx/
│   └── default.conf.j2
├── dnsmasq/
│   ├── Dockerfile
│   └── cove.conf.j2
├── vault/
│   └── vault.hcl
├── files/
│   └── actions/
│       ├── configure-pages/action.yml
│       ├── deploy-pages/action.yml
│       └── upload-pages-artifact/action.yml
├── seeds/
│   └── vault-user.yaml
├── bringup.yml
├── bootstrap_vault.yml
├── provision_vault_user.yml
├── provision_forgejo.yml
└── provision_pages.yml
```

Static files (no machine-specific values) stay as-is in the resource bundle. Templates (`.j2`) are rendered at extraction time with defaults.

### 2. Add `cove init` command

```
cove init
  ├─ Creates ~/.config/cove/compose/
  ├─ Extracts resources from package to ~/.config/cove/compose/
  ├─ Renders .j2 templates with defaults (no PII)
  ├─ Runs `ansible-galaxy collection install community.docker` if missing
  └─ Writes ~/.config/cove/config.toml
```

`cove up` auto-runs `cove init` if `~/.config/cove/compose/` doesn't exist.

### 3. Update `cove up` resource resolution

`cove up` resolves the compose directory in priority order:
1. `~/.config/cove/compose/` (installed mode)
2. `compose/` relative to CWD (dev mode, fallback)

Ansible is invoked with:
- `ansible-playbook -i <dir>/inventory.yml <dir>/bringup.yml`
- `ANSIBLE_ROLES_PATH=<dir>/roles`
- `compose_dir` var set to the resolved path

`docker compose` is invoked from the resolved directory so relative paths in `docker-compose.yml` resolve correctly.

### 4. Add Ansible as a documented host prerequisite

Ansible is required on the host for `cove up`. The CLI checks for it and prints install instructions if missing. The `community.docker` collection is installed by `cove init` via `ansible-galaxy`.

### 5. Clean up tracked rendered files

- `git rm --cached cli/cove/__pycache__/` (already gitignored, remove from tracking)
- `git rm --cached compose/dnsmasq/cove.conf` (rendered output, add to .gitignore)
- `git rm compose/files/cove-sudoers` (PII, delete from repo)
- Add `compose/dnsmasq/cove.conf` to `.gitignore`
- Add `compose/nginx/default.conf` to `.gitignore` (rendered from template)

### 6. Update pyproject.toml

```toml
[tool.setuptools.package-data]
"cove.resources" = ["**/*"]
```

### 7. Update CLI code

- `cli/cove/cli.py`: add `init` subcommand, update `up` to resolve resource paths
- `cli/cove/project.py`: update AGENTS.md injection to reference `~/.config/cove/` paths
- `cli/cove/templates/`: remove if empty after migration (all templates move to `resources/compose/`)

## Verification

1. `uv tool install .` then `cove up` works on a fresh machine (Ansible must be installed)
2. `uv run --directory cli cove up` (dev mode) still works via relative path fallback
3. No PII in tracked files
4. `~/.config/cove/compose/` contains the full compose directory tree
5. `docker compose` relative paths resolve correctly from `~/.config/cove/compose/`
6. Ansible playbooks find roles, group_vars, and inventory correctly
7. All 66 tests pass

## Deferred

- `~/.config/cove/config.toml` user preferences (FQDN override, etc.) — minimal for now
- `~/.config/cove/state.json` for health checks — not needed yet
- User template overrides in `~/.config/cove/templates/` — not needed yet
- Removing `compose/` from the repo root entirely — keep it for dev mode fallback until the migration is stable