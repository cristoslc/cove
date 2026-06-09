---
title: Cove Architecture
created: 2026-05-09
authored-by: deepseek-v4-pro:cloud
status: Active
---

# Cove Architecture

Cove is a portable, offline-capable local developer platform. It runs Forgejo (Git), Vault (secrets), CI runners, a container registry, and a static pages server — all from a single Docker Compose file. The current track targets macOS via Docker Desktop with Tailscale for remote access. A future track migrates to k3s.

## System Boundaries

```
                          Host (macOS)
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│  /etc/hosts          cove CLI (uv tool install)             │
│  /etc/resolver/      ├─ creds vault-put / vault-get        │
│                      └─ [up/down/build   ← future]          │
│                                                             │
│  ┌─── Docker Compose ────────────────────────────────────┐  │
│  │                                                        │  │
│  │  nginx (:80 → 301, :443 TLS)   dnsmasq (:5353)       │  │
│  │   ├─ git.cove.{ts.net}  → forgejo:3000                │  │
│  │   └─ *.pages.cove.{ts.net} → /data/pages/sites/      │  │
│  │                                                        │  │
│  │  forgejo (:3000)         vault (:8200)                │  │
│  │   SQLite, TLS certs       Shamir 5/3, age-encrypted   │  │
│  │                                                        │  │
│  │  ~/Documents/cove-data/  ← bind mounts                │  │
│  │    forgejo/ vault/ pages/ certs/ nginx/ dnsmasq/       │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                             │
│  Tailscale daemon                     1Password CLI         │
│   ├─ serve → https://localhost:443     └─ op item get       │
│   └─ MagicDNS: mbpbk-202602.taila90e7.ts.net                │
│                                                             │
│  OS Keychain                                                 │
│   └─ cove/vault/unseal-{1..5}, cove/vault/root-token        │
└─────────────────────────────────────────────────────────────┘
```

### What Cove Owns

- Docker Compose file defining the service stack.
- Ansible playbooks for provisioning (`compose/`).
- Python CLI for credential operations (`cli/`).
- Nginx configuration for HTTPS reverse proxy.
- dnsmasq configuration for offline wildcard DNS.
- Tailscale Serve configuration (managed by `bringup.yml`).
- `/etc/hosts` entries and `/etc/resolver/` configuration.
- OS keychain entries for Vault unseal keys and root token.

### What Cove Does Not Own

- The Docker Desktop installation (prerequisite).
- The Tailscale daemon (prerequisite).
- The 1Password CLI (prerequisite).
- Python 3.12+ and uv (prerequisites).
- `~/Documents/projects/` — user project directories.

## Bounded Contexts

Cove's domain splits into five contexts. Each owns its vocabulary, its storage, and its entry point. Contexts communicate only through declared interfaces — a pipeline in Forge reads secrets from Vault via the CLI, pushes artifacts to the Registry, and the Pages context serves them. No context reaches into another's storage directly.

### Forge Context

The source of truth for code and collaboration. Owns repositories, issues, pull requests, workflows, releases. Everything in Cove starts with a git push to the forge. The forge triggers pipelines and records their outcomes. It is the only context that creates identities (`<owner>/<repo>`).

| Aspect | Detail |
|--------|--------|
| Language | repository, issue, pull request, workflow, runner, webhook |
| Storage | SQLite database + git repositories on disk |
| Entry point | `https://git.cove.mbpbk-202602.taila90e7.ts.net` |
| Implementation | Forgejo v15 |

### Vault Context

The source of truth for secrets at rest. Caches credentials from 1Password so pipelines run offline. Owns secret storage, access tokens, and the unseal lifecycle. The vault is never exposed to any network — it is only accessible from the CLI on localhost. No other context stores secrets. No other context generates tokens.

| Aspect | Detail |
|--------|--------|
| Language | secret, mount, path, token, unseal, shamir, policy |
| Storage | Raft (on-disk, `~/Documents/cove-data/vault/data/`) |
| Entry point | `cove creds vault-put` / `vault-get` (CLI on `127.0.0.1:8200`) |
| Implementation | HashiCorp Vault 1.20 |

### Runtime Context

Executes pipelines. Owns runner lifecycle, job dispatch, build environments, and isolation guarantees. The runtime pulls source from the forge, reads secrets from the vault (via the CLI), executes steps, and pushes artifacts to the registry. It is the only context that runs untrusted code.

| Aspect | Detail |
|--------|--------|
| Language | runner, job, step, pipeline, sandbox, isolation |
| Storage | Ephemeral (containers destroyed after job completion) |
| Entry point | Forgejo Actions runner |
| Implementation | Forgejo runner (Docker), Kata Containers (future) |

### Registry Context

Stores build outputs. Owns container images and their lifecycle — pull, cache, serve. The registry is the bridge between building an image and deploying it. It is the only context that stores binary artifacts.

| Aspect | Detail |
|--------|--------|
| Language | image, tag, layer, pull, push, cache |
| Storage | Forgejo data directory (`~/Documents/cove-data/forgejo/`) |
| Entry point | `forgejo.cove.local/v2/` |
| Implementation | Forgejo built-in OCI registry |

### Pages Context

Serves static sites. Owns site artifacts, subdomain routing, and the deploy-publish-serve lifecycle. Three composite actions (`configure-pages`, `upload-pages-artifact`, `deploy-pages`) replicate GitHub Pages behavior. The pages context only reads artifacts pushed by pipelines — it never builds them.

| Aspect | Detail |
|--------|--------|
| Language | site, page, artifact, deploy, subdomain, redirect |
| Storage | `~/Documents/cove-data/pages/sites/<owner>/<repo>/` |
| Entry point | `https://<owner>.pages.cove.mbpbk-202602.taila90e7.ts.net` |
| Implementation | nginx + dnsmasq (planned) |

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

The single entry point for all HTTP/HTTPS traffic. Terminates TLS on port 443 using Tailscale certs, redirects HTTP on port 80 to HTTPS. Routes by `Host` header:

| Host Pattern | Target |
|---|---|
| `git.cove.mbpbk-202602.taila90e7.ts.net` | `forgejo:3000` |
| `*.pages.cove.mbpbk-202602.taila90e7.ts.net` | `/data/pages/sites/` |

Vault is not routed through nginx — it is accessed directly by the CLI on `127.0.0.1:8200`.

### Git Forge (Forgejo)

Codeberg Forgejo v15 container. SQLite backend. TLS handled by nginx; Forgejo itself listens on port 3000. Key configuration:
- Registration disabled, sign-in required.
- Push-to-create enabled (user and org).
- SSH port 2222 published to `127.0.0.1:2222` bypassing the proxy, to keep SSH reachable offline.

### Secrets Vault (HashiCorp Vault)

Vault 1.20 with Raft storage. TLS disabled (reached via `127.0.0.1:8200`, never exposed to any network interface). Shamir unseal with 5 shares / 3 threshold. Unseal keys and root token stored in the host OS keychain. KV v2 engine at `secret/`. Age-encrypted backups via CronJob (future).

### Static Pages Server (planned)

A wildcard DNS resolver plus static file server that replicates GitHub Pages:
- dnsmasq resolves `*.cove.mbpbk-202602.taila90e7.ts.net` → `127.0.0.1` (offline fallback).
- nginx serves static content from `~/Documents/cove-data/pages/sites/<owner>/<repo>/`.
- MagicDNS handles the same wildcard online; dnsmasq is only consulted offline via `/etc/resolver/`.
- Three Forgejo composite actions (`cove/configure-pages`, `cove/upload-pages-artifact`, `cove/deploy-pages`) provide GitHub Pages workflow compatibility.

### CI Runners

Forgejo's built-in runner dispatches CI jobs to Docker containers on the same network. The k3s track adds Kata Containers with VM-level isolation for untrusted code from LLM agents.

### Container Registry (future)

The Registry context is implemented by Forgejo's built-in OCI-compatible container registry at the `/v2/` path. Woodpecker pipelines push images using `GITHUB_TOKEN` scoped to the project. Remote deploy targets authenticate with Forgejo PATs. A standalone `registry:2` container is not needed within Cove's scope — consumer projects (e.g., Homelab) deploy their own registries if required.

## DNS Strategy

### Online

Tailscale MagicDNS resolves `mbpbk-202602.taila90e7.ts.net` to the machine's Tailscale IP. MagicDNS natively resolves subdomains to the same machine, so `*.cove.mbpbk-202602.taila90e7.ts.net` all route to the Mac. Tailscale Serve forwards HTTPS traffic to `https://localhost:443` (nginx).

### Offline

MagicDNS is unreachable. Two mechanisms handle DNS offline:
- `/etc/hosts` maps the base MagicDNS FQDN to `127.0.0.1` for Forgejo access.
- `/etc/resolver/cove.mbpbk-202602.taila90e7.ts.net` routes subdomain queries to `dnsmasq:5353`, which has a wildcard `address=` rule resolving `*.cove.*.ts.net` → `127.0.0.1`.
- nginx at `127.0.0.1:443` uses locally cached Tailscale certs — valid TLS, CA-accepted, no warnings.

### Future (k3s)

The k3s migration introduces `.cove.local` as a cluster-local domain, resolved by CoreDNS inside the cluster and forwarded from the host via `/etc/resolver/` (macOS) or systemd-resolved (Linux). MagicDNS access continues in parallel for phone/Tailscale access. dnsmasq is removed; CoreDNS handles all internal resolution.

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
│   └── sites/           # Deployed static sites (planned)
│       └── <owner>/
│           ├── .index/  # User/org site
│           └── <repo>/  # Per-repository site
├── certs/
│   ├── fullchain.pem    # Tailscale TLS certificate
│   └── privkey.pem      # Tailscale TLS private key
├── nginx/
│   └── conf.d/
│       └── default.conf # Rendered from Ansible template
└── dnsmasq/
    └── cove.conf        # Wildcard resolver configuration
```

Files are backed up by existing tools (Time Machine, Syncthing, restic) that already capture `~/Documents/`.

## Provisioning Pipeline

Provisioning is Ansible-driven and sequential:

```
bringup.yml
  ├─ Renders .env
  ├─ Creates data directories
  ├─ Configures /etc/hosts
  ├─ Configures Tailscale Serve
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

provision_pages.yml (planned)
  ├─ Creates cove org in Forgejo
  ├─ Creates four repos (three actions + artifact store)
  ├─ Pushes action code
  └─ Registers workflow template
```

## Network Boundaries

| Service | External Access | Internal Access | Notes |
|---------|----------------|-----------------|-------|
| nginx | 127.0.0.1:443, :80 | internal Docker network | TLS termination, host-header routing |
| Forgejo HTTP | Via nginx only | `forgejo:3000` | No published host port |
| Forgejo SSH | 127.0.0.1:2222 | `forgejo:22` | Direct, not proxied |
| Vault | None | 127.0.0.1:8200 | CLI-only, no network exposure |
| dnsmasq | None | 127.0.0.1:5353 | Only resolves to 127.0.0.1 |
| Pages static files | Via nginx only | internal volume | Read-only from nginx container |

## TLS

Tailscale generates an HTTPS certificate for the MagicDNS FQDN via Let's Encrypt. The certificate is stored at `~/Documents/cove-data/certs/` and valid for the MagicDNS hostname and subdomains. Both nginx and Forgejo (pre-proxy) use this cert. Offline, the cert is still valid — the CA is trusted and the hostname resolves via `/etc/hosts`.

## Credential Lifecycle

```
1Password (op://Private/../password)
  │
  ├─ cove creds 1p-bulk-write → creates 1Password items
  │
  ├─ cove creds vault-put → caches in Vault KV v2
  │   └─ secret/data/op-cache/<vault>/<item>/<field>
  │
  └─ cove creds vault-get → reads from Vault cache
      └─ Used by Ansible provisioning tasks
```

The CLI reads `VAULT_TOKEN` from the environment or the OS keychain. If Vault is sealed, `vault-put` and `vault-get` automatically unseal it using keys from the keychain.

## Future: k3s Architecture

```
Host (macOS/Linux)
├── Lima VM (macOS only)
│   └── k3s single-node cluster
│       ├── namespace: cove
│       │   ├── forgejo (StatefulSet)          # Git + CI + OCI registry
│       │   ├── vault (StatefulSet + init-container unseal)
│       │   ├── runner (Deployment, Kata RuntimeClass)
│       │   └── traefik (Ingress Controller)
│       └── namespace: cove-draft-* (ephemeral)
└── ~/Documents/cove/ ← hostPath mounts
```

Key differences from the Compose MVP:
- Services are Kubernetes workloads, not Docker Compose services.
- Traefik replaces nginx as the ingress controller.
- CI runners use Kata Containers (VM per pod) for isolation.
- CoreDNS handles `.cove.local` as the sole internal DNS resolver.
- MagicDNS + Tailscale Serve still provide phone access.
