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

### What Cove Should Use

| Track | Recommended | Rationale |
|-------|-------------|-----------|
| **Current Docker Compose (macOS)** | Colima | Drop-in replacement. Free, FOSS, CLI-only, near-perfect Compose compat. |
| **Current Docker Compose (macOS, premium)** | OrbStack | Best UX, free for personal use, but closed-source and macOS-only. |
| **Current Docker Compose (Linux)** | Docker Engine | Native, free, perfect. No alternative needed. |
| **Future k3s (macOS)** | Lima VM (Ansible-managed) | Already planned in the design. k3s + containerd native. |

Colima is the pragmatic choice for the current track. It's FOSS, light, and changes nothing about how the pod is deployed. OrbStack is the nicer experience if you don't mind the macOS lock-in and closed source.

Rancher Desktop, Podman, and Finch are viable but add friction with no clear advantage over Colima for a 4-service compose stack. Raw Lima + nerdctl is the most authentic for the k3s future track but adds unnecessary complexity for the Compose present.