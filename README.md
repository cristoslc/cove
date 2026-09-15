# Cove

A local development platform running on Docker Compose — a sheltered harbor where code gets hosted, provisioned, and pushed before going to sea.

## Services

| Service | Purpose | Access |
|---------|---------|--------|
| **Forgejo** | Self-hosted Git forge with built-in OCI registry and commit signing | `https://git.cove.local/` |
| **HashiCorp Vault** | Secrets store with Shamir auto-unseal | `https://vault.cove.local/` |
| **nginx** | TLS termination and reverse proxy for all `*.cove.local` subdomains | `127.0.0.1:8443` (HTTPS), `:8080` (HTTP) |
| **dnsmasq** | Wildcard DNS resolver for offline `.cove.local` resolution | `127.0.0.1:5353` |
| **Forgejo Actions Runner** | CI runner for Forgejo Actions workflows (optional, outbound-only) | No ingress |
| **Speedtest Tracker** | Monitors the operator's WAN link (uptime/latency/bandwidth) | `https://speedtest.cove.local/` (optional) |
| **Observability** | Prometheus + Grafana metrics backend with OTLP ingestion for apps | `https://otel.cove.local/` |

All services run in Docker Compose with `restart: unless-stopped`. Configuration changes take effect on every `cove up`.

## Install

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

Cove is **not on PyPI**. Install from a GitHub release wheel (replace `v0.4.1` with the version you want):

```bash
uv tool install --from https://github.com/cristoslc/cove/releases/download/v0.4.1/cove_cli-0.4.1-py3-none-any.whl cove-cli
```

Releases are listed at <https://github.com/cristoslc/cove/releases>. The wheel for each version is attached as `cove_cli-<version>-py3-none-any.whl`.

> **Note:** the wheel bundles all compose resources. Reinstalling `cove` pulls updated compose — there is no separate deploy step.

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
| `cove up --no-sudo` | Same as above, skips `/etc/hosts` and pf NAT elevation |
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
  ├─ bringup              # Start Colima, TLS certs, /etc/hosts, docker compose up
  ├─ bootstrap_vault      # Initialize/unseal Vault from OS keychain
  ├─ provision_vault      # Userpass user + admin policy
  └─ provision_forgejo    # Admin user, SSH key, repo, push token
```

All data lives in `~/Documents/cove-data/`. TLS via cove certs with wildcard `*.cove.local` certificates. Tailscale Serve provides HTTPS access from any device on your tailnet via pf NAT forwarding (`127.0.0.1:443` → `8443`).

## Forgejo CLI

Cove uses Forgejo as its Git forge. The `fj` CLI manages repositories, pull requests, and more. See [Forgejo CLI Guide](docs/guides/fj-guide.md) for draft PR workflow and conventions.

## Architecture Docs

- [Architecture](docs/architecture.md) — system boundaries, bounded contexts, service topology, DNS strategy, data persistence
- [Abstractions](docs/abstractions.md) — domain concepts: project, pipeline, secret, image, site, deployment, identity, workspace
- [Forgejo Runner](docs/services/forgejo-runner.md) — optional CI runner for Forgejo Actions workflows
- [Pages](docs/services/pages.md) — static site hosting via Forgejo Actions and nginx
- [Data Inventory](docs/architecture/data-inventory.md) — every piece of state Cove holds, classified by source-of-truth and durability