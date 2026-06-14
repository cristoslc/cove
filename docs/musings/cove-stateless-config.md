# Cove Stateless Config

The repo has hardcoded config files that should be generated at runtime. Every time we find one, we have to scrub PII before pushing to GitHub. This is backwards.

## The constraint: uv tool install

`cove` is installed via `uv tool install cove-cli`. At runtime, there is **no repo checkout**. The only files available are the Python package itself and `~/.config/cove/`. This means:

- `cove up` cannot reference `compose/bringup.yml` by relative path
- Ansible playbooks, compose files, templates, action files, and seeds must all be **Python package resources**
- The CLI extracts them to `~/.config/cove/` on first run (or renders on the fly)
- `uv run --directory cli cove up` (dev mode) is the exception — it can use relative paths

## The principle

Cove's source repo should contain **no rendered config, no machine-specific state, no generated output**. Everything the CLI needs to run should be either:

1. A Python package resource (template, compose file, playbook, seed schema)
2. Rendered at `cove up` time from a Jinja2 template
3. A default value in the CLI code itself
4. A seed schema that the CLI fills from 1Password or env vars

State that *is* machine-specific goes to `~/.config/cove/` — not in the repo.

## What's currently wrong

| File | Problem | Fix |
|------|---------|-----|
| `compose/dnsmasq/cove.conf` | Rendered output of `cove.conf.j2` | Delete from repo, add to `.gitignore` |
| `compose/files/actions/*/action.yml` | Hardcoded Tailscale FQDN default | Template at push time, read FQDN from env or `~/.config/cove/config.toml` |
| `seeds/forgejo-creds.yaml` | Machine-specific SSH key paths | Generate from template at seed time |
| `compose/files/cove-sudoers` | Reference file with username | Delete from repo, generate instructions in CLI help text |
| `cli/cove/__pycache__/` | Build artifacts | Already gitignored, just need to `git rm --cached` |
| `compose/bringup.yml` (and all playbooks) | Referenced by path from CLI | Bundle as package resources, extract to `~/.config/cove/` on first run |
| `compose/docker-compose.yml` | Referenced by path from Ansible | Same — bundle as package resource |
| `compose/nginx/default.conf.j2` | Referenced by path from bringup.yml | Same — bundle as package resource |

## What goes where

```
~/.config/cove/
├── config.toml          # User preferences, FQDN overrides
├── state.json           # Last known service state (for health checks)
├── op-cache/            # 1Password credential cache
├── compose/
│   ├── docker-compose.yml
│   ├── bringup.yml
│   ├── bootstrap_vault.yml
│   ├── provision_vault_user.yml
│   ├── provision_forgejo.yml
│   ├── provision_pages.yml
│   ├── nginx/default.conf.j2
│   ├── dnsmasq/cove.conf.j2
│   ├── vault/vault.hcl
│   ├── files/actions/*/action.yml.j2
│   └── seeds/*.yaml.j2
└── templates/           # (optional) User overrides for any template
```

The repo keeps only:
```
cli/cove/
├── cli.py               # CLI entry point
├── templates/           # Jinja2 templates for rendered files
│   ├── bringup.yml.j2
│   ├── docker-compose.yml.j2
│   ├── ...
│   └── forgejo-creds.yaml.j2
├── resources/           # Static files (no machine-specific values)
│   └── actions/
│       └── upload-pages-artifact/
│           └── action.yml
└── project.py           # AGENTS.md injection
```

## What this enables

- Push to GitHub without PII scrub
- `uv tool install cove-cli && cove up` works on any machine — no repo needed
- No stale rendered configs (the dnsmasq conf problem)
- `~/.config/cove/` is the one place to back up or wipe
- Dev mode (`uv run --directory cli cove up`) still works via relative paths

## What it costs

- All playbooks, compose files, and templates must move from `compose/` to `cli/cove/templates/` as Jinja2-wrapped resources
- CLI needs an `extract` step on first run (or `cove init`) that unpacks resources to `~/.config/cove/`
- `cove up` must resolve resource paths: try `~/.config/cove/compose/` first, fall back to relative paths in dev mode
- Ansible playbooks need `vars` for resource paths (e.g., `compose_dir: "{{ cove_config_dir }}/compose"`)
- Migration: `git rm --cached` rendered files, add to `.gitignore`, move files, update CLI, verify dev mode and installed mode both work