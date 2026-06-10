# Docker Desktop Alternatives for Cove's Pod

Cove currently runs its pod (Forgejo, Vault, nginx, dnsmasq) via Docker Desktop on macOS. Docker Desktop is free for personal use (2026), but it's heavy (~2GB RAM idle), pushes Docker Inc's ecosystem, and periodically nags about licensing. This musing evaluates alternatives.

## The Stack

Cove's pod is a straightforward 4-service Docker Compose setup:
- forgejo:3000 (SQLite, bind mounts)
- vault:8200 (Shamir 5/3, age-encrypted unseal keys)
- nginx:443 (TLS termination, reverse proxy, static pages)
- dnsmasq:5353 (wildcard DNS for `.cove.ts.net`)

No Docker builds, no swarm, no Kubernetes. Just `docker compose up` with bind mounts and an internal network.

## Alternatives

| Option | macOS | Linux | Cost | Compose Compat. | RAM Idle | Notes |
|--------|-------|-------|------|-----------------|----------|-------|
| **Docker Desktop** | Yes | Yes | Free (personal) | Perfect | ~2GB | Nags about licensing. Bundles Kubernetes (unused). |
| **Colima** | Yes | N/A | Free (MIT) | Near-perfect | ~400MB | Runs real `dockerd` in a Lima VM. CLI only. `colima start` just works. |
| **OrbStack** | Yes | No | Free (personal), $8/mo (commercial) | Perfect | ~500MB | macOS-native (Swift, Apple Silicon). Starts in ~1s. Best UX. |
| **Rancher Desktop** | Yes | Yes | Free (Apache 2.0) | Good (Moby mode) | ~1GB | Bundles k3s. Can run `dockerd` (Moby) instead of containerd. Heavier than Colima. |
| **Podman** | Yes (VM) | Native | Free (Apache 2.0) | Partial | ~300MB | `podman machine` on macOS. `podman-compose` has edge cases with networking and volumes. Better on Linux. |
| **Finch** | Yes | Yes | Free (Apache 2.0) | Good (nerdctl) | ~400MB | AWS-backed. Lima + containerd + nerdctl. `finch compose` works but is nerdctl under the hood. |
| **Lima + nerdctl** | Yes | Yes | Free (Apache 2.0) | Partial | ~300MB | Raw Lima VM with containerd. `nerdctl compose` is less polished. CNCF Incubating. |

## Analysis

### Colima — The FOSS Sweet Spot

Colima runs real `dockerd` inside a Lima VM. `docker compose up` works identically to Docker Desktop. It's CLI-only (no GUI for logs), but with a 4-service stack that's not a burden. ~400MB RAM idle vs Docker Desktop's ~2GB. MIT licensed, active development, ~24K GitHub stars.

For Cove's current Docker Compose track, Colima is a drop-in replacement — same compose files, same bind mounts, same `docker compose up`. The only difference is `colima start` replaces opening Docker Desktop.app.

### OrbStack — The Premium Option

OrbStack is macOS-native (Swift, Apple Silicon optimizations). It starts in ~1s, dynamically allocates RAM, and has the best UX of any option. Free for personal use (commercial is $8/mo). If Cove stays solo and personal, OrbStack is free forever.

It runs real Docker Engine + Compose under the hood, so compatibility is perfect. But it's closed-source and macOS-only. If Cove ever needs Linux support, OrbStack won't work.

### Docker Engine (Linux) — The Baseline

On Linux, `docker-ce` + `docker compose` plugin is free, native, and perfect. No VM overhead, no licensing questions. The k3s future track will use containerd directly anyway. This is the reference implementation — all other options are trying to replicate this experience on macOS.

## Rethinking k3s: Is It Wrong for This Use Case?

The k3s track was designed assuming Cove would need CI runners with Kata Containers, NetworkPolicies, Kaniko jobs, and containerd image mirroring. But that's a "maybe" — and the RAM cost of k3s is paid upfront regardless of whether you use those features.

### k3s + Lima RAM Budget (macOS)

| Layer | RAM | Notes |
|-------|-----|-------|
| Lima VM | 1-2GB | Linux VM needs baseline memory |
| k3s control plane | 500MB-1GB | apiserver, scheduler, controller-manager, etcd |
| CoreDNS + Traefik | ~150MB | Cluster infrastructure |
| **Overhead subtotal** | **~1.5-3GB** | Before any actual services |
| Forgejo + Vault + nginx + dnsmasq | ~300MB | The actual pod |
| **Total** | **~1.8-3.3GB** | |

### Lightweight Alternatives

| Approach | macOS | Linux | RAM (idle) | CI Possible? | Complexity |
|----------|-------|-------|------------|--------------|------------|
| **Colima + docker compose** | Lima + dockerd | N/A | ~400MB | Yes (standalone runner container) | Low |
| **OrbStack + docker compose** | Native | N/A | ~500MB | Yes (standalone runner container) | Low |
| **Lima + containerd + nerdctl compose** | Lima VM | Native | ~300MB | Yes (standalone runner container) | Medium |
| **k3s in Lima** | Lima VM | Native | ~1.5-3GB | Yes (native k8s runners, Kata, Kaniko) | High |
| **Docker Engine** | N/A | Native | ~200MB | Yes (standalone runner container) | Low |

### Rethinking the k3s Assumption

k3s was designed into Cove's architecture based on an implicit assumption: "you need k8s to get CI runners." But Forgejo runners are **not k8s runners** — they're standalone Docker containers that register with Forgejo via a token. They don't need a Kubernetes cluster.

You get CI by running:
```
docker run -d \
  -e FORGEJO_RUNNER_TOKEN=$(cove creds vault-get FORGEJO_RUNNER_TOKEN) \
  -e FORGEJO_INSTANCE_URL=https://git.cove.local \
  codeberg.org/forgejo/runner:15
```

That's it. No k3s, no Kata, no NetworkPolicy. The runner container runs alongside Forgejo on the same Docker network. If you want VM-level isolation later, you could colima start --runtime=containerd + nerdctl with Kata — but you don't need it for day 1.

### When Does k3s Actually Make Sense?

| You want k3s when... | Lightweight alternative |
|---------------------|------------------------|
| CI with untrusted code (Kata) | Skip until you have untrusted CI. Runner containers share Docker socket trust by default. |
| NetworkPolicies between services | Compose networks are isolated by default. Not needed. |
| Kaniko daemonless builds | `docker build` works in Compose. Kaniko is only needed if you're building inside a CI container without a Docker socket. |
| containerd image mirror (offline) | Useful but not critical. Pre-pull images explicitly. |
| `cove tryup` (compose-to-k8s conversion) | Just use `docker compose up` directly. |
| Composing two projects on different hosts | Not relevant for a single-user local platform. |

### Pragmatic Path Forward

| Phase | Stack | RAM | Rationale |
|-------|-------|-----|-----------|
| **Now** | Colima + docker compose + standalone runner container | ~400MB | Works today, minimal overhead, CI works |
| **If offline caching needed** | Same + script to pre-pull images into Forgejo's OCI registry | ~400MB | No extra daemon |
| **If VM isolation needed** | Colima with containerd runtime + Kata | ~500MB | Same VM, different runtime |
| **If k8s becomes essential** | Lima + k3s | ~1.5-3GB | Migrate when the need is proven, not before |

The k3s architecture doc should be reframed as an **escalation path**, not the default target. The default target should be the lightest thing that works — currently Colima + docker compose, eventually whatever comes after.

### Absolute Lightest Option: Lima + nerdctl Compose

If you don't even want `dockerd`'s overhead, Lima can run containerd natively with `nerdctl compose`. This is what Finch does under the hood. ~300MB idle. `nerdctl compose` handles basic compose files well, though it has rough edges with health checks, multi-file overrides, and some volume configurations. For Cove's 4-service stack (no health checks, single compose file, simple bind mounts), it would likely work fine.

But Colima wraps this with a polished UX (`colima start`, `colima stop`) and runs standard `docker compose` — so the practical difference is negligible.

### Recommendation

**Default to Colima for macOS, Docker Engine for Linux.** Keep `docker compose up` as the deployment mechanism. Don't introduce k3s until a specific feature requires it (Kata isolation, Kaniko, etc.). The overhead isn't justified for a 4-service pod serving a solo developer.

## UX Gap: Losing Docker Desktop's Health Visibility

Colima is CLI-only — no GUI for container logs, resource usage, or restart buttons. Docker Desktop's dashboard, for all its bloat, gives you at-a-glance container health. Moving to Colima means that disappears.

### Options to Fill the Gap

| Approach | Pros | Cons |
|----------|------|------|
| **Cove health daemon** (`docs/musings/cove-health-daemon.md`) | Built for Cove, minimal deps, self-heals on restart | Async loop + Docker SDK to write; own it forever |
| **Portainer** | Rich web UI, active project, FOSS (BSL-2.0) | Runs as a container managing containers — meta, feels wrong. BSL license has enterprise terms that may shift. |
| **LazyDocker** | TUI, lightweight, keyboard-driven | Another tool to install, terminal-only, not Cove-integrated |
| **Nothing — trust the daemon** | Health daemon restarts on failure; don't need a GUI if you don't look | Silent if you don't run `cove status` |

### Portainer Hesitation

Portainer is the obvious "add a UI" answer, but:
- It's a container managing your containers — if Docker goes down, Portainer goes with it (not useful for the crash-loop case).
- BSL 2.0 license has enterprise conversion clauses (MongoDB-style rugpull risk).
- It's a full web app for what should be a `cove status` command.

### What This Means for the Health Daemon

The health daemon (`docs/musings/cove-health-daemon.md`) goes from "nice to have" to **part of the migration prerequisite**. Without it, moving from Docker Desktop to Colima is a UX regression — you lose the GUI and gain nothing in return. The daemon is the replacement for that visual feedback loop. Its priority should be elevated to: build it before or alongside the Colima migration.

**See also:** [`docs/musings/cove-health-daemon.md`](cove-health-daemon.md) — the health daemon fills the observability gap Colima creates.