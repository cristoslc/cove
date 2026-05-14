# Cove

A local development platform running on Docker Compose — a sheltered harbor where code gets hosted, provisioned, and pushed before going to sea.

## Services

| Service | Purpose | Access |
|---------|---------|--------|
| **Forgejo** | Self-hosted Git forge with commit signing | `https://{machine}.taila90e7.ts.net:3000` (Tailscale) or `https://localhost:3000` |
| **HashiCorp Vault** | Secrets store with Shamir auto-unseal | `http://127.0.0.1:8200` |

Both run in Docker Compose with `recreate: always` so configuration changes (env vars, volumes) take effect on every `cove up`.

## Install

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv tool install cove
```

## Quick Start

```bash
cove up --no-sudo        # Bring up containers, bootstrap Vault, provision Forgejo
cove up --no-provision   # Bring up containers only (skip Forgejo setup)
cove down                # Stop containers, keep data
cove down --volumes      # Stop containers and remove volumes
cove uninstall --yes     # Destroy everything: containers, data, keychain, cache
```

## Commands

| Command | Purpose |
|---------|---------|
| `cove up` | Full pipeline: batch-pull → bringup → bootstrap Vault → provision Forgejo |
| `cove up --no-sudo` | Same as above, skips `/etc/hosts` elevation |
| `cove up --no-provision` | Bring up containers only |
| `cove down` | Stop containers (data preserved) |
| `cove down --volumes` | Stop containers and remove volumes |
| `cove uninstall --yes` | Destroy all cove containers, data, keychain entries, and cache |
| `cove creds batch-pull` | Pull all 1Password refs in one biometric prompt (cached to disk) |
| `cove creds vault-get <ref>` | Read a cached op:// reference |
| `cove creds 1p-bulk-write <spec> --execute` | Seed 1Password items from a YAML spec |
| `cove project install` | Inject cove service guidance into AGENTS.md |
| `cove project install -g` | Same, but into global `~/.claude/CLAUDE.md` |

## Architecture

```
cove up
  ├─ batch-pull           # One biometric prompt for all 1Password refs
  ├─ bringup              # docker compose up (Forgejo + Vault)
  ├─ bootstrap_vault.yml  # Initialize/unseal Vault from OS keychain
  ├─ provision_vault.yml  # Userpass user + admin policy
  └─ provision_forgejo.yml # Admin user, SSH key, repo, manual merge
```

All data lives in `~/Documents/cove-data/`. Tailscale MagicDNS provides HTTPS access from any device on your tailnet.

## Project Artifacts

| Artifact | Status | Description |
|----------|--------|-------------|
| [VISION-001](docs/vision/Proposed/(VISION-001)-Cove-Developer-Platform/(VISION-001)-Cove-Developer-Platform.md) | Active | Cove Developer Platform — full local dev stack vision |

(End of file - total 54 lines)
