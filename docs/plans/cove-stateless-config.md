# Plan: Cove Stateless Config

**Date:** 2026-06-14
**Based on:** `docs/musings/cove-stateless-config.md`

**Problem:** Cove is installed via `uv tool install cove-cli` but its playbooks, compose files, and templates are referenced by relative path from the repo checkout. Hardcoded config files contain PII (username, Tailscale FQDN) that must be scrubbed before pushing to GitHub. The repo should contain only templates and Python resources — no rendered config, no machine state.

**Goal:** All runtime resources (playbooks, compose files, templates, action files, seeds) are bundled as Python package resources. The CLI extracts them to `~/.config/cove/` on first run. Dev mode (`uv run --directory cli cove up`) continues to work via relative paths.

## Changes

### 1. Move resources from `compose/` to `cli/cove/templates/`

Move all playbooks, compose files, and templates into the Python package as Jinja2-wrapped resources:

- `compose/bringup.yml` → `cli/cove/templates/compose/bringup.yml.j2`
- `compose/bootstrap_vault.yml` → `cli/cove/templates/compose/bootstrap_vault.yml.j2`
- `compose/provision_vault_user.yml` → `cli/cove/templates/compose/provision_vault_user.yml.j2`
- `compose/provision_forgejo.yml` → `cli/cove/templates/compose/provision_forgejo.yml.j2`
- `compose/provision_pages.yml` → `cli/cove/templates/compose/provision_pages.yml.j2`
- `compose/docker-compose.yml` → `cli/cove/templates/compose/docker-compose.yml.j2`
- `compose/nginx/default.conf.j2` → `cli/cove/templates/compose/nginx/default.conf.j2`
- `compose/dnsmasq/cove.conf.j2` → `cli/cove/templates/compose/dnsmasq/cove.conf.j2`
- `compose/vault/vault.hcl` → `cli/cove/templates/compose/vault/vault.hcl.j2`
- `compose/group_vars/all.yml` → `cli/cove/templates/compose/group_vars/all.yml.j2`
- `compose/inventory.yml` → `cli/cove/templates/compose/inventory.yml.j2`
- `compose/roles/os_keystore/` → `cli/cove/templates/compose/roles/os_keystore/`
- `compose/files/actions/configure-pages/action.yml` → `cli/cove/templates/compose/files/actions/configure-pages/action.yml.j2`
- `compose/files/actions/deploy-pages/action.yml` → `cli/cove/templates/compose/files/actions/deploy-pages/action.yml.j2`
- `compose/files/actions/upload-pages-artifact/action.yml` → `cli/cove/templates/compose/files/actions/upload-pages-artifact/action.yml.j2`
- `compose/seeds/vault-user.yaml` → `cli/cove/templates/compose/seeds/vault-user.yaml.j2`
- `seeds/forgejo-creds.yaml` → `cli/cove/templates/seeds/forgejo-creds.yaml.j2`

Static files (no machine-specific values) stay as-is:
- `compose/files/actions/upload-pages-artifact/action.yml` (no FQDN or paths)

### 2. Add `cove init` command

New CLI subcommand that extracts resources to `~/.config/cove/`:

```
cove init
  ├─ Creates ~/.config/cove/compose/
  ├─ Renders templates with defaults (no machine-specific values)
  ├─ Prompts for FQDN override (optional)
  └─ Writes ~/.config/cove/config.toml
```

`cove up` auto-runs `cove init` if `~/.config/cove/` doesn't exist.

### 3. Update `cove up` resource resolution

`cove up` resolves resource paths in priority order:
1. `~/.config/cove/compose/` (installed mode)
2. `compose/` relative to CWD (dev mode, fallback)

Ansible playbooks receive `compose_dir` var pointing to the resolved path.

### 4. Clean up tracked rendered files

- `git rm --cached cli/cove/__pycache__/` (already gitignored, just remove from tracking)
- `git rm --cached compose/dnsmasq/cove.conf` (rendered output, add to .gitignore)
- `git rm compose/files/cove-sudoers` (PII, delete from repo)
- Add `compose/dnsmasq/cove.conf` to `.gitignore`

### 5. Update pyproject.toml

Add package data config to include templates:

```toml
[tool.setuptools.package-data]
"cove.templates" = ["**/*"]
```

## Verification

1. `uv tool install .` then `cove up` works on a fresh machine
2. `uv run --directory cli cove up` (dev mode) still works
3. No PII in tracked files
4. `~/.config/cove/compose/` contains all playbooks and templates
5. All 66 tests pass

## Deferred

- `~/.config/cove/config.toml` user preferences (FQDN override, etc.) — minimal for now, just the extraction path
- `~/.config/cove/state.json` for health checks — not needed yet
- User template overrides in `~/.config/cove/templates/` — not needed yet