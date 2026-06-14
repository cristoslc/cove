# Cove Stateless Config

The repo has hardcoded config files that should be generated at runtime. Every time we find one, we have to scrub PII before pushing to GitHub. This is backwards.

## The principle

Cove's source repo should contain **no rendered config, no machine-specific state, no generated output**. Everything the CLI needs to run should be either:

1. A template (`.j2`, `.yml.j2`) that gets rendered at `cove up` time
2. A default value in the CLI code itself
3. A seed schema that the CLI fills from 1Password or env vars

State that *is* machine-specific goes to `~/.config/cove/` — not in the repo.

## What's currently wrong

| File | Problem | Fix |
|------|---------|-----|
| `compose/dnsmasq/cove.conf` | Rendered output of `cove.conf.j2` | Delete from repo, add to `.gitignore` |
| `compose/files/actions/*/action.yml` | Hardcoded Tailscale FQDN default | CLI should template these at push time, or read FQDN from env |
| `seeds/forgejo-creds.yaml` | Machine-specific SSH key paths | CLI should generate from template, fill paths at runtime |
| `compose/files/cove-sudoers` | Reference file with username | Delete from repo, generate instructions in CLI help text |
| `cli/cove/__pycache__/` | Build artifacts | Already gitignored, just need to `git rm --cached` |

## What goes where

```
~/.config/cove/
├── config.toml          # User preferences, FQDN overrides
├── state.json           # Last known service state (for health checks)
├── op-cache/            # 1Password credential cache
└── templates/           # (optional) User overrides for any template
```

The repo keeps only:
```
compose/
├── docker-compose.yml   # Static, no machine-specific values
├── dnsmasq/
│   └── cove.conf.j2     # Template, rendered at bringup time
├── nginx/
│   └── default.conf.j2  # Template, rendered at bringup time
├── files/actions/
│   ├── configure-pages/
│   │   └── action.yml.j2  # Template, rendered at push time
│   ├── deploy-pages/
│   │   └── action.yml.j2
│   └── upload-pages-artifact/
│       └── action.yml     # Static, no machine-specific values
└── seeds/
    └── forgejo-creds.yaml.j2  # Template, rendered at seed time
```

## What this enables

- Push to GitHub without PII scrub
- `git clone && cove up` works on any machine
- No stale rendered configs (the dnsmasq conf problem)
- `~/.config/cove/` is the one place to back up or wipe

## What it costs

- CLI needs a `render` step for action files before pushing to Forgejo
- `provision_pages.yml` needs to render templates before pushing
- Migration: `git rm --cached` the rendered files, add to `.gitignore`, verify nothing breaks