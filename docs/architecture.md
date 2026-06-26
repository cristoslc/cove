---
title: Cove Architecture
created: 2026-05-09
authored-by: deepseek-v4-pro:cloud
status: Active
---

# Cove Architecture

Cove is a portable, offline-capable local developer platform. It runs Forgejo (Git), Vault (secrets), a container registry (built into Forgejo), CI runners, and a static pages server — all from a single Docker Compose file on Colima (macOS) or Docker Engine (Linux).

## System Boundaries

```
                          Host (macOS/Linux)
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│  /etc/hosts          cove CLI (uv tool install)             │
│  /etc/resolver/      ├─ creds vault-put / vault-get         │
│                      └─ up / down / uninstall               │
│                                                             │
│  ┌─── Docker Compose ────────────────────────────────────┐  │
│  │                                                        │  │
│  │  nginx (:8080 → 301, :8443 TLS)   dnsmasq (:5353)    │  │
│  │   ├─ git.cove       → forgejo:3000                    │  │
│  │   ├─ vault.cove     → vault:8200                      │  │
│  │   ├─ hc.cove        → health check                    │  │
│  │   └─ *.pages.cove   → /data/pages/sites/              │  │
│  │                                                        │  │
│  │  forgejo (:3000)         vault (:8200)                 │  │
│  │   SQLite, OCI registry    Shamir auto-unseal            │  │
│  │                                                        │  │
│  │  ~/Documents/cove-data/  ← bind mounts                 │  │
│  │    forgejo/ vault/ pages/ certs/ nginx/ dnsmasq/        │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                             │
│  pf NAT: 127.0.0.1:443 → 127.0.0.1:8443                    │
│  Tailscale Serve → https://127.0.0.1:443 (if tailnet)      │
│                                                             │
│  Cove PKI             OS Keychain                            │
│   └─ *.cove, localhost  └─ cove/vault/unseal-{1..5}        │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### What Cove Owns

- Docker Compose file defining the service stack (`compose/docker-compose.yml`)
- Ansible playbooks for provisioning (`compose/`)
- Python CLI for credential and lifecycle operations (`cli/`)
- Nginx configuration for HTTPS reverse proxy (`compose/nginx/`)
- dnsmasq configuration for offline wildcard DNS (`compose/dnsmasq/`)
- Cove PKI certificates for `*.cove` subdomains
- `/etc/hosts` entries and `/etc/resolver/` configuration
- OS keychain entries for Vault unseal keys and root token
- pf NAT rule forwarding `localhost:443` → `localhost:8443`

### What Cove Does Not Own

- The container runtime (Colima on macOS, Docker Engine on Linux)
- The Tailscale daemon (optional, for remote access)
- The 1Password CLI (optional, for credential seeding)
- Python 3.12+ and uv
- `~/Documents/projects/` — user project directories

## Bounded Contexts

Cove's domain splits into five contexts. Each owns its vocabulary, its storage, and its entry point. Contexts communicate only through declared interfaces — a pipeline in Forge reads secrets from Vault, pushes artifacts to the Registry, and the Pages context serves them. No context reaches into another's storage directly.

### Forge Context

The source of truth for code and collaboration. Owns repositories, issues, pull requests, workflows, releases, and the OCI container registry. Everything in Cove starts with a git push to the forge.

| Aspect | Detail |
|--------|--------|
| Language | repository, issue, pull request, workflow, runner, webhook |
| Storage | SQLite database + git repositories on disk |
| Entry point | `https://git.cove/` |
| Implementation | Forgejo v15 |

### Vault Context

The source of truth for secrets at rest. Caches credentials from 1Password so pipelines run offline. Owns secret storage, access tokens, and the unseal lifecycle. Accessed through nginx at `https://vault.cove/` — no direct host port exposure.

| Aspect | Detail |
|--------|--------|
| Language | secret, mount, path, token, unseal, shamir, policy |
| Storage | Raft (on-disk, `~/Documents/cove-data/vault/data/`) |
| Entry point | `https://vault.cove/` (via nginx) |
| Implementation | HashiCorp Vault 1.20 |

### Runtime Context

Executes pipelines. Owns runner lifecycle, job dispatch, build environments, and isolation guarantees. Pulls source from the forge, reads secrets from the vault, executes steps, and pushes artifacts to the registry.

| Aspect | Detail |
|--------|--------|
| Language | runner, job, step, pipeline, sandbox, isolation |
| Storage | Ephemeral (containers destroyed after job completion) |
| Entry point | Forgejo Actions runner |
| Implementation | Forgejo runner (Docker) |

### Registry Context

Stores build outputs as OCI artifacts. Owns container images and their lifecycle — pull, cache, serve. Implemented by Forgejo's built-in OCI registry at `/v2/` — no separate `registry:2` container.

| Aspect | Detail |
|--------|--------|
| Language | image, tag, layer, pull, push, cache |
| Storage | Forgejo data directory (`~/Documents/cove-data/forgejo/`) |
| Entry point | `https://git.cove/v2/` |
| Implementation | Forgejo built-in OCI registry |

### Pages Context

Serves static sites. Owns site artifacts, subdomain routing, and the deploy-publish-serve lifecycle. Three composite actions (`configure-pages`, `upload-pages-artifact`, `deploy-pages`) replicate GitHub Pages behavior.

| Aspect | Detail |
|--------|--------|
| Language | site, page, artifact, deploy, subdomain, redirect |
| Storage | `~/Documents/cove-data/pages/sites/<owner>/<repo>/` |
| Entry point | `https://<owner>.pages.cove/` |
| Implementation | nginx + dnsmasq |

### Context Map

```
1Password ──→ Vault ──→ Runtime ──→ Registry
                  ↑         │            │
                  │         │            ▼
              Forge ────────┘        Deployment
                  │
                  └──→ Pages ──→ Browser
```

| Upstream | Downstream | Relationship |
|----------|-----------|-------------|
| 1Password | Vault | Supplier — Vault caches what 1Password owns |
| Vault | Runtime | Supplier — Runtime reads secrets during build |
| Forge | Runtime | Conformist — Runtime conforms to Forge's workflow model |
| Runtime | Registry | Supplier — Runtime pushes build artifacts |
| Registry | Deployment | Supplier — Deployment pulls images from Registry |
| Runtime | Pages | Supplier — Runtime pushes static site artifacts |
| Pages | Browser | Supplier — Pages serves files to end users |

## Service Topology

### Reverse Proxy (nginx)

The single entry point for all HTTP/HTTPS traffic. Terminates TLS on port 8443 (host) using Cove PKI certificates, redirects HTTP on port 8080 to HTTPS. pf NAT forwards `localhost:443` → `8443`. Routes by `Host` header:

| Host Pattern | Target |
|---|---|
| `git.cove` | `forgejo:3000` |
| `vault.cove` | `vault:8200` |
| `hc.cove` | health check (200 OK) |
| `*.pages.cove` | `/data/pages/sites/` |
| Tailscale FQDN | `forgejo:3000` (conditional) |

### Git Forge (Forgejo)

Codeberg Forgejo v15 container. SQLite backend. TLS handled by nginx; Forgejo itself listens on port 3000. SSH port 2222 published to `0.0.0.0:2222` directly, bypassing the proxy.

### Secrets Vault (HashiCorp Vault)

Vault 1.20 with Raft storage. Accessible only through nginx at `https://vault.cove/` — no host port mapping. Shamir unseal with 5 shares / 3 threshold. Unseal keys and root token stored in the host OS keychain. KV v2 engine at `secret/`.

### Static Pages Server

A wildcard DNS resolver plus static file server that replicates GitHub Pages:
- dnsmasq resolves `*.pages.cove` → `127.0.0.1`.
- nginx serves static content from `~/Documents/cove-data/pages/sites/<owner>/<repo>/` with Cove PKI wildcard TLS.
- Three Forgejo composite actions (`cove/configure-pages`, `cove/upload-pages-artifact`, `cove/deploy-pages`) provide GitHub Pages workflow compatibility.

### CI Runners

Forgejo's built-in runner dispatches CI jobs to Docker containers on the same network. No separate runner container is deployed yet.

### Container Registry

Forgejo's built-in OCI-compatible container registry at the `/v2/` path. Pipelines push images using `GITHUB_TOKEN` scoped to the project. Remote deploy targets authenticate with Forgejo PATs. A standalone `registry:2` container is not needed within Cove's scope.

## DNS Strategy

### Online

All `*.cove` domains resolve via `/etc/hosts` to `127.0.0.1`. Tailscale MagicDNS resolves the Tailscale FQDN to the machine's Tailscale IP; Tailscale Serve forwards HTTPS to `https://127.0.0.1:8443`.

### Offline

- `/etc/hosts` maps `cove`, `git.cove`, `vault.cove`, `hc.cove` to `127.0.0.1`.
- `/etc/resolver/cove` routes subdomain queries to `dnsmasq:5353`, which has a wildcard rule resolving `*.cove` → `127.0.0.1`.
- nginx at `127.0.0.1:8443` uses Cove PKI certs — valid TLS, CA-accepted, no warnings.

## Data Persistence

All persistent state lives under `~/Documents/cove-data/`:

```
~/Documents/cove-data/
├── forgejo/
│   ├── gitea/           # Forgejo database and config
│   ├── git/             # Git repositories
│   └── ssh/             # SSH host keys
├── vault/
│   ├── data/            # Vault Raft storage
│   └── logs/            # Vault audit logs
├── pages/
│   └── sites/           # Deployed static sites
│       └── <owner>/
│           ├── .index/  # User/org site
│           └── <repo>/  # Per-repository site
├── certs/
│   ├── cove.local.pem    # Cove PKI TLS certificate
│   └── cove.local-key.pem # Cove PKI TLS private key
├── nginx/
│   └── conf.d/
│       └── default.conf  # Rendered from Ansible template
└── dnsmasq/
    └── cove.conf         # Wildcard resolver configuration
```

Files are backed up by existing tools (Time Machine, Syncthing, restic) that already capture `~/Documents/`.

## Provisioning Pipeline

Provisioning is Ansible-driven and sequential:

```
bringup.yml
  ├─ Starts Colima (macOS)
  ├─ Configures Cove PKI TLS for *.cove
  ├─ Creates data directories
  ├─ Configures /etc/hosts
  ├─ Configures pf NAT (443 → 8443)
  ├─ Configures Tailscale Serve (if tailnet)
  ├─ Renders .env + nginx + dnsmasq configs
  ├─ docker compose up (forgejo, vault, nginx, dnsmasq)
  └─ Waits for health

bootstrap_vault.yml
  ├─ Initializes Vault (Shamir 5/3)
  ├─ Stores unseal keys + root token in OS keychain
  ├─ Unseals Vault
  └─ Enables KV v2 at secret/

provision_vault_user.yml
  └─ Creates userpass user for Vault UI

provision_forgejo.yml
  ├─ Completes Forgejo install
  ├─ Generates admin API token
  ├─ Creates SSH key + registers with Forgejo
  └─ Sets up known_hosts

provision_pages.yml
  ├─ Creates cove org in Forgejo
  ├─ Creates action repos (configure-pages, upload-pages-artifact, deploy-pages)
  ├─ Pushes action code
  └─ Registers workflow template
```

## Network Boundaries

| Service | External Access | Internal Access | Notes |
|---------|----------------|-----------------|-------|
| nginx | `127.0.0.1:8443`, `:8080` | Internal Docker network | TLS termination, host-header routing |
| Forgejo HTTP | Via nginx only | `forgejo:3000` | No published host port |
| Forgejo SSH | `0.0.0.0:2222` | `forgejo:22` | Direct, not proxied |
| Vault | Via nginx only | `vault:8200` | No host port mapping |
| dnsmasq | None | `127.0.0.1:5353` | Only resolves to `127.0.0.1` |
| Pages static files | Via nginx only | Internal volume | Read-only from nginx container |

## TLS

Cove generates a locally-trusted CA and certificates for `*.cove`, `localhost`, `127.0.0.1`, `::1` using Python's `cryptography` library. Stored at `~/Documents/cove-data/certs/`. The root CA is installed into the system trust store automatically. If Tailscale is available, its Tailscale FQDN certificate is also loaded for remote access via tailnet URLs.

## Credential Lifecycle

```
1Password (op://Private/../password)
  │
  ├─ cove creds 1p-bulk-write → creates 1Password items
  │
  ├─ cove creds batch-pull → writes disk cache
  │   └─ ~/.cove/op-cache/<vault>/<item>/<field>
  │
  ├─ cove creds vault-put → caches in Vault KV v2
  │   └─ secret/data/op-cache/<vault>/<item>/<field>
  │
  └─ cove creds vault-get → reads from Vault cache
      └─ Used by Ansible provisioning tasks
```

The CLI reads `VAULT_TOKEN` from the environment or the OS keychain. If Vault is sealed, `vault-put` and `vault-get` automatically unseal it using keys from the keychain.