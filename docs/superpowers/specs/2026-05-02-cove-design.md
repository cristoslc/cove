---
title: Cove Design
author: cristoslc
parent: EPIC-???-cove
state: draft
---

# Cove Design

## Purpose

Cove is a portable, offline-capable local developer platform running on k3s — a sheltered harbor where code gets built, tested, and deployed before going to sea. It provides Forgejo, Vault, CI runners, Forgejo's built-in OCI registry, and tools for building source. All services run inside containers or VMs. Nothing new runs on the host.

It replaces the `infrastructure/local-pod/` Docker Compose stack in the Homelab repo. Cove is a **local developer platform**, not shared infrastructure. It must work on any machine with no external dependencies, and must back up all data to `~/Documents/` for automated backup capture.

## Threat Model

All code running in CI is treated as untrusted. This includes code written by LLM agents and code cloned from public repositories. The platform must prevent a compromised CI job from accessing the host filesystem, the host network, or other services in the cluster.

## Design Overview

### Architecture

```
Host (macOS/Linux/SteamOS)
├── ~/Documents/projects/                  # Normal git repos
│   └── git remote → git.cove.local        # Forgejo in k3s
│
├── Host resolver config (managed by Ansible)
│   └── .cove.local → k3s node IP          # No new daemon
│
├── k3s (single-node cluster)
│   │
│   │ On macOS: inside Lima VM (Ansible-managed)
│   │ On Linux: native k3s on host
│   │
│   └── namespace: cove
│       ├── forgejo (StatefulSet)          # Git + CI + OCI registry
│       ├── vault (StatefulSet)            # Secrets cache
│       ├── runner (Deployment)            # CI runners (sandboxed)
│       ├── traefik (Ingress)             # HTTP only; SSH blocked
│       └── kaniko (Job templates)        # Build source offline
│
│   └── namespace: cove-draft-* (ephemeral) # Converted compose experiments
│
└── cove CLI                               # compose-to-k8s, kaniko build
```

### Principles

| Principle | Rule |
|-----------|------|
| **No host services** | All network-listening services run in k3s. Host only provides filesystem and resolver config. |
| **Fully offline** | All images stored in Forgejo's OCI registry. Builder images cached. No external pulls during normal use. |
| **Data in Documents** | All persistent state is on host filesystem under `~/Documents/` via `hostPath` or bind mounts. Backed up by existing tools (Syncthing, Time Machine, etc.). |
| **Untrusted CI** | CI runners use Kata Containers (VM per pod) for isolation from the host kernel. |
| **Cloud patterns** | CI runners, NetworkPolicy, StatefulSets, sidecars, init containers. All standard k8s. |
| **Experiment-first** | `docker-compose.yml` → raw k8s manifests via `cove draft`. No Helm required for experiments. |

## Components

### Forgejo (StatefulSet)

- Runs as a `StatefulSet` with a `hostPath` volume mounted to `~/Documents/cove/forgejo/data`
- SQLite backend (single-node k3s, no need for PostgreSQL complexity)
- `NetworkPolicy`: allow ingress on HTTP (80/443) only. SSH (22) is not exposed via Ingress. Only accessible from within the cluster if needed by runners.
- CI runners connect as separate `Deployment` pods, not in-container

### Vault (StatefulSet)

- `hostPath` volume at `~/Documents/cove/vault/data`
- Init container handles unseal using key shards from `~/Documents/cove/vault/secrets/` (age-encrypted, synced)
- `NetworkPolicy`: no ingress from outside the cluster. Only Forgejo runners and the host (via `kubectl port-forward` or NodePort on loopback) may access.

### Runner (Deployment with Kata RuntimeClass)

- Forgejo runner agents as a `Deployment` with `replicas: 1` default
- **Uses Kata Containers RuntimeClass** (`katacontainers.io/kata-runtime`). Each runner pod gets its own lightweight VM.
- Mounts `~/Documents/projects/` as `hostPath` for access to project source during builds
- `NetworkPolicy`: egress allowed only to Forgejo and Vault. No general internet access.
- Scale via `kubectl scale` for parallel CI

### Traefik (Ingress Controller)

- Only handles HTTP/HTTPS
- No TCP route for SSH (enforces the "HTTP on Tailscale, SSH blocked" policy)
- Forgejo web UI: `https://git.cove.local`

### Kaniko (Job Templates)

- Builds from source without a Docker daemon
- Job mounts `~/Documents/projects/<project>` as `hostPath`
- Pushes output to Forgejo's OCI registry (`git.cove.local/v2/` with GITHUB_TOKEN auth)
- Triggered via cove CLI: `cove build <project-path>`

## VM Layer (macOS Only)

On macOS, k3s runs inside a Lima VM managed by the cove Ansible role.

### Why a VM

macOS uses the Darwin kernel. Containers need Linux. A VM provides:
- A Linux kernel for containerd and Kata Containers
- An extra isolation boundary between containers and the host
- A stable network IP for the host to reach k3s services

### Lima VM Spec

```yaml
# Lima VM template (managed by Ansible role)
cpus: 4
memory: 8GiB
disk: 60GiB
mounts:
  - location: ~/Documents/cove
    writable: true
  - location: ~/Documents/projects
    writable: true
networks:
  - lima: shared
    # Provides stable IP 192.168.5.2
```

The VM is created by the `shared/roles/cove/tasks/darwin.yml` task file. It uses the `limactl` CLI installed by the same role. The k3s binary is downloaded, SHA-verified, and installed inside the VM by Ansible (not by Lima's built-in scripts, so we control the version).

### Kata Containers in the VM

Kata Containers 3.x requires a Linux kernel with KVM. The Lima VM provides this. The cove role installs Kata alongside k3s and registers the `kata` RuntimeClass. Only runner pods use this RuntimeClass. Platform pods (Forgejo, Vault, Traefik) use the default `runc` runtime for performance.

## DNS Strategy

No new host daemons. Use existing OS resolver infrastructure:

| OS | Mechanism | Config managed by Ansible |
|---|---|---|
| macOS | mDNSResponder + `/etc/resolver/` | `/etc/resolver/cove.local` → `nameserver 192.168.5.2` |
| Linux | systemd-resolved | `/etc/systemd/resolved.conf.d/cove.conf` → `DNS=127.0.0.1` |
| Fallback | `/etc/hosts` | Static entries for critical services |

The target IP:
- macOS with Lima: `192.168.5.2` (Lima VM shared network)
- Linux native: `127.0.0.1` with NodePort

CoreDNS inside k3s resolves `.cove.local` to cluster services. The host resolver forwards that domain to the k3s node.

## Data Persistence & Backup

All state lives under `~/Documents/cove/`:

```
~/Documents/cove/
├── forgejo/
│   └── data/                     # Forgejo data, repos, config
├── vault/
│   ├── data/                     # Vault storage backend
│   └── secrets/
│       ├── unseal-keys.age      # Age-encrypted unseal shards
│       └── root-token.age       # Age-encrypted root token
└── backups/
    └── auto-dumps/              # Periodic Vault snapshots, Forgejo dumps
```

- `hostPath` volumes map these directly into pods.
- Backup tools (Syncthing, Time Machine, restic) already capture `~/Documents/`.
- No separate backup strategy needed. These are just files in Documents.
- **Vault auto-dump**: A CronJob in k3s periodically runs `vault operator raft snapshot save` to `~/Documents/cove/backups/auto-dumps/`. These are encrypted with age if they contain sensitive data.

## The Tryout Workflow

```bash
# Phase 1: Tryout (ephemeral)
cd /tmp
git clone https://github.com/cool/project.git
cd project
cove tryup .
# → reads docker-compose.yml
# → generates raw manifests (Deployment, Service, ConfigMap)
# → applies to namespace cove-draft-7a3f
# → prints URL: http://project.cove.local

# Phase 2: Adoption (if you decide to keep it)
# 1. Copy generated manifests to cove repo
# 2. Replace emptyDir with proper hostPath PVC
# 3. Add to GitOps / apply workflow
# 4. `kubectl delete namespace cove-draft-7a3f`
```

The `cove tryup` command uses `kompose` or a custom parser to convert Compose to k8s. The output is **raw manifests**, not Helm. For permanent services, you can later wrap them in Helm or Kustomize.

## Integration with Workstation Repo

The `202604-workstation` repo gets a new role:

```
shared/roles/cove/
├── defaults/main.yml          # Pinned k3s version, Kata version, ports
├── tasks/
│   ├── main.yml               # OS dispatch
│   ├── darwin.yml             # Lima install, VM create, k3s install
│   ├── debian.yml             # Native k3s install
│   ├── install-lima.yml       # Download + verify limactl
│   ├── install-k3s.yml        # Download + verify k3s binary
│   ├── install-kata.yml       # Download + verify Kata, register RuntimeClass
│   ├── configure-network.yml  # Host resolver, CoreDNS custom zone
│   └── deploy-platform.yml    # Apply cove manifests, install cove CLI
├── templates/
│   ├── lima-k3s.yaml.j2       # Lima VM spec
│   ├── k3s-config.yaml.j2     # k3s server config (disable traefik, etc.)
│   ├── containerd-kata.toml.j2 # containerd drop-in for Kata runtime
│   ├── coredns-custom.yml      # CoreDNS ConfigMap for .cove.local
│   └── traefik-values.yml.j2   # Traefik Helm values (HTTP only)
└── files/
    ├── k3s-checksums.txt      # SHA256 for pinned k3s version
    └── kata-checksums.txt     # SHA256 for pinned Kata version
```

The role:
1. Installs Lima (macOS) or verifies native k3s prerequisites (Linux)
2. Creates Lima VM (macOS) or installs k3s directly (Linux)
3. Installs k3s inside the VM with pinned version + SHA verification
4. Installs Kata Containers and registers the `kata` RuntimeClass
5. Configures host resolver for `.cove.local`
6. Downloads and installs the `cove` CLI from GitHub releases
7. Deploys the `cove` namespace with manifests
8. Creates `~/Documents/cove/` directory structure

## Project Workflow

For a project like `~/Documents/projects/south-portland-school-budget-FY27/`:

```bash
# Add local forge as remote
git remote add local http://git.cove.local/school/budget-fy27.git

# Push to local first — CI runs in k3s runners
git push local main

# Local Forgejo runs checks (lint, tests, review)
# If checks pass, push to cloud
git push origin main
```

The project itself is just files on disk. The Forgejo runner mounts `~/Documents/projects/` as a `hostPath` volume and runs CI inside a Kata VM pod.

## Runner Isolation (Kata Containers)

### Why Kata

Standard containers share the host kernel. A kernel exploit in a CI job (running untrusted code from an LLM) compromises the entire node. Kata Containers runs each pod in its own lightweight VM, providing kernel isolation.

### What Runs in Kata

| Pod | Runtime | Reason |
|---|---|---|
| Forgejo | runc | Trusted code. Performance matters. |
| Vault | runc | Trusted code. No user input. |
| Traefik | runc | Trusted code. Edge proxy. |
| **Runner** | **kata** | **Untrusted code. LLM output. Needs kernel isolation.** |
| Kaniko Job | kata | Builds arbitrary source. Same threat model as runner. |
| Tryout pods | kata | Unknown code from the internet. |

### Kata Configuration

- containerd config drop-in at `/var/lib/rancher/k3s/agent/etc/containerd/config.toml.tmpl`
- RuntimeClass `kata` with handler `kata-qemu` or `kata-clh` (Cloud Hypervisor, lighter than QEMU)
- Resource overhead: ~128MB memory per VM, ~1s cold start
- `hostPath` volumes still work (9p/virtiofs mount into the VM)

## Network Segmentation

| Service | Ingress | Tailscale | LAN | Notes |
|---|---|---|---|---|
| Forgejo HTTP | Traefik | Yes | Yes | Via HTTPS on tailnet domain |
| Forgejo SSH | None | No | No | Only cluster-internal if needed |
| Vault | None | No | No | `kubectl port-forward` or NodePort on loopback only |
| Tryouts | Traefik | Yes | Yes | Per-namespace ingress |
| Runner egress | — | No | No | NetworkPolicy: only to Forgejo, Vault |

## Gap Analysis: Current (local-pod) vs Target (cove)

### What Exists (local-pod in Homelab repo)

| Component | Status | Location |
|---|---|---|
| Forgejo container | Running | Docker Compose, `~/Documents/code/cove/compose/docker-compose.yml` (migrated from Homelab local-pod) |
| Vault container | Running | Docker Compose, `infrastructure/local-pod/docker-compose.yml` |
| Ansible bringup | Working | `infrastructure/local-pod/bringup.yml` |
| Vault bootstrap | Working | `infrastructure/local-pod/bootstrap_vault.yml` |
| Forgejo provisioning | Migrated | `infrastructure/local-pod/provision_forgejo.yml` — no longer needed; Forgejo runs in cove compose |
| Tailscale serve | Working | Managed by Ansible playbook |
| CLI creds integration | Working | `cli/lab/creds.py` (vault-put, vault-get) |
| SSH key caching | Working | `scripts/cache-ssh-keys-in-vault.sh` |

### What Must Be Built or Migrated

| Component | Action | Notes |
|---|---|---|
| **Lima install (macOS)** | Build new | No equivalent. Ansible downloads + verifies limactl binary. |
| **Lima VM creation** | Build new | No equivalent. VM spec template, stable IP, hostPath mounts. |
| **k3s install** | Build new | No equivalent. Download + verify + install inside VM (macOS) or on host (Linux). |
| **Kata Containers install** | Build new | No equivalent. Download + verify + containerd drop-in + RuntimeClass registration. |
| **Host resolver config** | Build new | Ansible task. No new daemon. |
| **Forgejo StatefulSet** | Migrate from Compose | Convert `compose/docker-compose.yml` to k8s StatefulSet. Add `hostPath` for data. Forgejo v15 already migrated from Homelab local-pod into cove compose. |
| **Vault StatefulSet** | Migrate from Compose | Convert to StatefulSet. Add init container for unseal. Add auto-snapshot CronJob. |
| **Runner Deployment (Kata)** | Build new | No equivalent. Kata RuntimeClass + restricted NetworkPolicy. |
| **Registry Deployment** | N/A | Superseded by Forgejo's built-in OCI registry — no standalone registry needed. |
| **Traefik Ingress** | Build new | No equivalent. Replaces Tailscale serve for HTTP routing. NetworkPolicy blocks SSH. |
| **Kaniko Job template** | Build new | No equivalent. Enables offline source builds. |
| **CoreDNS custom config** | Build new | Add `.cove.local` zone to k3s CoreDNS. |
| **Workstation CLI** | Build new | `cove build`, `cove tryup`. Replaces `lab` CLI for local operations. |
| **Ansible role (`cove`)** | Build new | In workstation repo. Lima + k3s + Kata + network + platform deploy + CLI install. |
| **Data migration** | Done | Forgejo data already migrated from local-pod to `~/Documents/code/cove/compose/data/`. |
| **Tailscale serve removal** | Deprecate | Replaced by Traefik ingress. Tailscale still provides overlay. |

### What Can Be Reused

| Component | Reuse | Notes |
|---|---|---|
| Vault bootstrap logic | Adapt | `bootstrap_vault.yml` logic → init container or Job. Unseal keys stay in `~/Documents/`. |
| Forgejo provisioning | N/A | Already provisioned. `provision_forgejo.yml` no longer needed. Forgejo runs in cove compose with `INSTALL_LOCK=true`. |
| SSH key caching script | Reuse | `cache-ssh-keys-in-vault.sh` still valid. Target Vault moves to cluster DNS. |
| Seeds (`seeds/forgejo-creds.yaml`) | N/A | Config lives in compose-mounted `data/forgejo/gitea/conf/app.ini`, not via seed files. |
| Download-and-verify pattern | Reuse | `shared/tasks/download-and-verify.yml` for k3s, Kata, Lima binaries. |

### Key Gaps to Address

| Gap | Risk | Mitigation |
|---|---|---|
| **Kata overhead** | ~128MB memory and ~1s cold start per CI job. | Acceptable for untrusted code isolation. Only runners use Kata; platform services use runc. |
| **Lima VM disk space** | VM disk grows with images and Forgejo registry data. | Start with 60GiB. Expand via Lima disk resize. Data in `~/Documents/` (outside VM). |
| **Offline image caching** | First run needs internet to pull base images. | Pre-pull script during setup. Forgejo registry stores everything. Builder images (kaniko, distroless, Kata guest kernel) pre-cached in Forgejo. |
| **Compose-to-k8s conversion** | May not handle all Compose features. | Document limitations. Use `kompose` as base, extend for common patterns. |
| **Vault unseal on restart** | k3s node reboot seals Vault. | Init container reads unseal keys from `~/Documents/` (age-encrypted). Auto-unseal on pod restart. |
| **Runner image size and caching** | Runner needs git, languages, tools. Custom image. | Build runner image once, push to Forgejo registry, cache forever. |
| **Kata guest kernel images** | Kata needs guest kernel + initrd images. | Pre-pull during setup. Store in Forgejo registry or VM disk. |

## Decision: Name

The namespace, directory, domain, and CLI are all named **`cove`**.

- `cove` is the CLI binary distributed via GitHub releases.
- `.cove.local` is the cluster-local DNS domain.
- `~/Documents/cove/` is the persistent data directory.
- The Ansible role in the workstation repo is `shared/roles/cove/`, which pulls the `cove` binary from `https://github.com/cristoslc/cove/releases`.
- Single-word project name — distinctive and searchable.

## Risks & Open Questions

| Risk | Status |
|---|---|
| Kata on Apple Silicon | Kata 3.x supports arm64. Cloud Hypervisor (clh) is lighter than QEMU. Test before committing. |
| Lima VM suspend/resume | Lima does not auto-suspend. VM runs until stopped. Acceptable for a dev server. |
| kaniko vs. buildkit for source builds | TBD. kaniko is daemonless and works in restricted environments. buildkit may be faster. Evaluate in spike. |
| Vault auto-unseal security | Unseal keys on disk (encrypted) vs. manual unseal. Trade-off for "works offline." |
| Kata + hostPath performance | 9p/virtiofs is slower than bind mounts. Test with real CI workloads. |

## Dependencies

- `kubectl` and `helm` (installed by workstation role)
- `age` (already in workstation for SOPS)
- `kompose` or custom parser (for `cove tryup`)
- `limactl` (installed by cove role on macOS)

## Out of Scope

- Multi-node k8s (this is single-node by design)
- Cloud deployment of this platform (it's specifically local)
- Replacing Docker Compose for the Thor homelab (that's a separate stack)
- Devcontainers (explicitly out; we use sidecars for tooling instead)
- Windows support (WSL2 is a different beast; tackle later if needed)

## Related Artifacts

- `infrastructure/local-pod/` — current stack (to be deprecated)
- `docs/superpowers/specs/2026-04-30-dev-role-local-pod-design.md` — prior spec for Docker Compose approach (superseded by this)
- `docs/runbook/Proposed/(RUNBOOK-009)-Cache-SSH-Key-In-Vault/` — Vault workflow (reusable)
- `202604-workstation` repo — target home for the Ansible role and CLI
