---
title: "Cove Platform Core"
artifact: EPIC-001
track: container
status: Proposed
author: cristos
created: 2026-05-03
last-updated: 2026-05-03
parent-vision: VISION-001
priority-weight: high
success-criteria:
  - cove binary responds to up, down, build, and tryup commands
  - cove up starts k3s and deploys Forgejo, Vault, and CI services
  - cove build produces a container image via Kaniko without internet access
  - cove tryup deploys a docker-compose project to the local k3s cluster
depends-on-artifacts: []
addresses: []
evidence-pool: ""
---

# Cove Platform Core

## Goal / Objective

Ship a working `cove` binary that bootstraps a complete local development platform with a single command, and provides essential subcommands for building and deploying workloads.

## Desired Outcomes

A developer can check out any project, run `cove up`, and have a working local platform within minutes. The cove binary serves as the single entry point for managing the entire local stack — no need to run kubectl, docker, or manual k3s configuration.

## Scope Boundaries

**In scope:**
- cove Python package installed via `uv tool install`
- Click-based CLI with up, down, build, tryup subcommands
- Lima VM management (macOS)
- k3s single-node cluster provisioning
- Platform services: Forgejo (Git), Vault (secrets), CI runners (Kata Containers)
- Local image registry (Harbor-like via Docker Registry)
- Kaniko integration for daemonless container builds

**Out of scope:**
- Go-based binary (superseded by Python/uv approach)
- Production deployment
- Multi-node clusters
- User authentication with external IdPs
- Networking beyond single-node (LoadBalancer, Ingress with external IPs)

## Child Specs

- SPEC-001: Cove Binary CLI

## Key Dependencies

- Lima (macOS) or native k3s (Linux) for cluster provisioning
- age encryption for Vault auto-unseal
- Kata Containers for CI runner isolation

## Lifecycle

| Phase | Date | Commit | Notes |
|-------|------|--------|-------|
| Proposed | 2026-05-03 | | Initial creation |