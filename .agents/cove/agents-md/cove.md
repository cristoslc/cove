# Cove (project-level)

This file augments/overrides the global cove spoke doc (`~/.agents/agents-md-detail/cove.md`) for the cove repository itself. Consult the global doc first for CLI reference, credential management, and general troubleshooting.

## Local dev workflow

### Running cove locally

```bash
# Start all services
cove up

# Stop all services
cove down

# Check version
cove version
```

### Development cycle

1. Make changes to roles, playbooks, or CLI.
2. Re-run `cove up` to rebuild containers if role/playbook source changed.
3. For CLI changes, the `cove` command is installed from source — rebuild and reinstall:

```bash
poetry build && pip install --force-reinstall dist/*.whl
```

or use the dev install:

```bash
poetry install
```

### Composed services

The compose file is at `compose/docker-compose.yml`. It defines:

- Forgejo (git server)
- Vault (secret storage)
- Woodpecker CI
- Container registry
- Pages

### CI / Playbooks

CI configuration lives in `.woodpecker/` at the repo root (Woodpecker-style YAML). Playbooks under `playbooks/` automate provisioning steps.

### Credential provisioning

See `seeds/` for initial secrets and `playbooks/` for automated setup workflows. Run:

```bash
cove creds batch-pull
```

after a fresh `cove up` to populate Vault with all required secrets.

## Overrides vs. global

| Aspect | Global doc | This doc |
|--------|------------|----------|
| CLI reference | Full `cove` and `fjl` docs | Dev build/install |
| Credential flow | `vault-get`/`vault-put` chain | Seed data locations |
| Troubleshooting | General service issues | Repo-specific |
| CI constraints | No internet during builds | File locations |

When in doubt, start with the global doc and use this file for repo-specific context.
