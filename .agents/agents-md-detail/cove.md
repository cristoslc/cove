# Cove

This machine runs Cove — a local developer platform (forge, vault, CI, registry, pages).
All services are offline-first. The same FQDN resolves locally and over Tailscale.

## Forgejo

- Web: `http://localhost:3000/`
- CLI: use `fj` (auto-detects host from git remote — see `.agents/agents-md-detail/fj.md` for full reference)

## Vault / Credentials

Never hardcode secrets. Use:
- `cove creds vault-get op://vault/item/field` — read a cached secret
- `cove creds vault-put op://vault/item/field` — cache a 1Password secret into Vault
- `cove creds batch-pull` — refresh all cached refs in one batch (single biometric prompt)

Vault address: `http://127.0.0.1:8200`

## CLI reference

| Command | Description |
|---------|-------------|
| `cove up` | Bring up cove containers and provision Forgejo |
| `cove down` | Stop cove containers |
| `cove creds vault-get <opref>` | Read a cached secret from Vault |
| `cove creds vault-put <opref>` | Cache a 1Password secret into Vault |
| `cove creds batch-pull` | Pull all known op:// refs in one batch |
| `cove install` | Inject cove guidance into AGENTS.md |
| `cove uninstall` | Destroy all cove containers, data, and credentials |

## Constraints

- Do not add cloud dependencies.
- Do not assume internet access during builds or CI.
- All git remotes go to Forgejo at `localhost`.
