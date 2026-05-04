---
title: "Cove Developer Platform"
artifact: VISION-001
track: standing
status: Active
product-type: personal
author: cristos
created: 2026-05-03
last-updated: 2026-05-03
priority-weight: high
depends-on-artifacts: []
evidence-pool: ""
---

# Cove Developer Platform

## Target Audience

Solo developer who needs a full local dev stack — Git forge, secrets management, CI runners, container registry — running on a single-node k3s cluster without installing anything new on the host machine.

## Value Proposition

Cove turns a plain workstation into a self-contained, offline-capable developer platform. When connectivity is unreliable or unavailable, all services (forge, vault, CI, registry) keep running locally. No external dependencies, no vendor lock-in, no cloud bill.

## Problem Statement

Every time a developer switches projects or loses connectivity, they lose access to critical development infrastructure. CI runners are tied to external services, secrets live in cloud vaults, and container images need internet access to pull. This creates friction when working offline, traveling, or just wanting a stable local environment.

## Existing Landscape

- Cloud CI (GitHub Actions, GitLab CI) requires internet and external account access.
- Local Docker Compose setups are ad-hoc and not portable across machines.
- k3s exists but requires significant manual configuration to get a full dev platform running.
- No single tool manages the full stack from zero to working platform.

## Build vs. Buy

1. **Find an existing solution**: No single tool covers the full stack (forge + vault + CI + registry) as an offline-first, zero-config local platform. Solutions like Tilt, DevSpace, or Docker Desktop cover only parts.
2. **Glue-code existing tools**: Could compose k3s + Forgejo + Vault + Harbor manually, but the configuration complexity is high and not portable.
3. **Build from scratch**: Cove is the chosen path — a Python package installed via `uv tool install` that bootstraps the full platform on Lima (macOS) or native k3s (Linux), with sensible defaults and offline-first design.

## Maintenance Budget

One person (the author). Any architectural choice must be maintainable without a team. Simplicity and obvious behavior are primary virtues.

## Success Metrics

- A fresh checkout can run `uv tool install cove` and then `cove up` to have a working Forgejo, Vault, and CI runner within 10 minutes.
- The platform survives a network outage without degrading or requiring manual intervention.
- Container images build from source via Kaniko without internet access.
- Python 3.12+ and uv are the only host dependencies — no compiled binary required.

## Non-Goals

- Cove does not target production deployments. It is a local development tool only.
- Multi-node clusters are out of scope.
- User authentication integration with external identity providers is not a goal.

## Lifecycle

| Phase | Date | Commit | Notes |
|-------|------|--------|-------|
| Active | 2026-05-03 | | Initial creation |