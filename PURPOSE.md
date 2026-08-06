---
title: "Cove — Purpose & Identity"
created: 2026-05-09
authored-by: deepseek-v4-pro:cloud
status: Active
---

# Cove

Cove is a local developer platform for one person. One command gives you a working forge, vault, CI runner, container registry, static pages server, and observability backend (Prometheus + Grafana with OTLP ingestion) — all running locally, all working offline, nothing on the cloud.

## Identity

Cove is a **harbor**. It is the line between your machine and everything you need to build software. Nothing runs on the host. Everything runs inside the harbor — a forge, a vault, runners, a registry, pages, observability. They arrive together, wired to each other, with no manual assembly. When the outside world disappears — no WiFi, no cell signal — everything inside keeps working.

## Core Concepts

These ideas repeat everywhere in Cove. They are not architecture or implementation — they are what Cove believes.

### Harbor

Everything runs inside Cove. Nothing runs on the host. When something enters the harbor (a repo clone, a secret, an image), it stays available even when the outside world disappears. The harbor's boundary is also the deployment boundary — Cove does not give you individual services to configure. It gives you one thing: one install, one command, one working platform.

### Offline by Default

The internet is optional. Every operation works without a network connection. Offline is not degraded mode — it is the normal mode. Network access is an enhancement, not a prerequisite.

The test: on an airplane with WiFi off, can you still do everything you'd do at your desk?

### Single Developer

Cove is for one person. No teams, no roles, no RBAC, no multi-tenancy. Forgejo registrations are disabled. Vault has one user. The CI runner is a single agent. This constraint eliminates entire categories of complexity and lets every service use its simplest configuration.

"Single developer" does not mean "single machine" — you might access Cove from your phone or share a page with a friend. But there is one owner, one identity, one admin.

### Data in Documents

All persistent state lives under `~/Documents/`. Plain directories on the host filesystem, mounted into containers as bind mounts. Not `/var/`, not `~/.local/`, not inside opaque Docker volumes. Standard backup tools (Time Machine, Syncthing, restic, iCloud Drive) already capture `~/Documents/` — Cove inherits backup and disaster recovery for free.

### One Address, Everywhere

Every service has a single FQDN. That FQDN is the same whether you are on the host machine, on your phone, or disconnected from every network. What changes is how the name resolves — dnsmasq and local resolver config offline, with MagicDNS or Tailscale Split DNS as an enhancement when present. The consumer never sees the difference.

### Self-Contained

Cove requires exactly three things from the host: Python, uv, and a container runtime (Colima on macOS, Docker Engine on Linux). Everything else — services, certificates, DNS, runners — is brought and managed by Cove. Uninstalling means deleting the containers and the data directory. Nothing is left in system paths, launch daemons, or hidden dotfiles.

Third-party services (Tailscale, cloud DNS, etc.) may enhance Cove when present — remote access, encrypted transit, zero-config discovery — but Cove MUST NOT build on them as foundational infrastructure. A third-party rugpull (pricing change, account lockout, API deprecation, free-tier restriction) must not break Cove's core. Enhancement layer, not foundation.

## Audience

A solo developer who switches between projects and locations. Someone who writes code on planes, in cafés, at cabins. Someone who wants a CI pipeline and a container registry without a cloud account. Someone who is the entire team.

Cove is not for teams, not for production, not for multi-node clusters.

## What Cove Is

- **A platform, not a toolkit.** One install, one command, working forge + vault + CI + registry + pages + observability.
- **Offline by default.** Every operation works without internet. Network access is a bonus, not a requirement.
- **Self-contained.** Three host prerequisites. Cove brings everything else and leaves no trace when removed.
- **Opinionated.** Cove makes the choices so you don't have to — SQLite, not Postgres; Shamir, not cloud auto-unseal; nginx, not Traefik (until k3s).

## What Cove Is Not

- A production deployment target.
- A team platform (no RBAC, no multi-tenancy, no IdP integration).
- A Kubernetes distribution (k3s is the runtime, not the product).
- A replacement for cloud CI (it's the local complement to it).
- A managed service (you run it, you own the data).
- **A development environment.** Cove does not ship coding harnesses, editors, LSPs, language runtimes, or any tool that reads/writes your source code. Cove is infrastructure — it provides the services development tools connect to (forge, vault, CI, registry, pages, observability). The tools themselves are the operator's responsibility (or a companion project's).

## Guiding Principle

If it needs the internet to work, it is not done.

If it needs you to configure three things before it runs, it is not done.

If it runs on the host instead of inside the harbor, it is not done.
