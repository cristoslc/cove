---
title: "Cove Binary CLI"
artifact: SPEC-001
track: implementable
status: Proposed
author: cristos
created: 2026-05-03
last-updated: 2026-05-03
priority-weight: high
parent-epic: EPIC-001
linked-artifacts: []
depends-on-artifacts: []
addresses: []
evidence-pool: ""
swain-do: required
---

# Cove Binary CLI

## Problem Statement

The developer needs a single entry point to manage the entire Cove platform — starting and stopping the local k3s cluster, building container images from source, and deploying docker-compose projects to the local cluster. Without a unified CLI, managing the platform requires juggling multiple tools and manual steps.

## Desired Outcomes

A developer can run `cove up` and have a working platform with no additional configuration. They can run `cove build .` to build a container image from the current directory and see it available in the local registry. They can run `cove tryup .` to deploy a docker-compose project to their local k3s cluster for testing.

## Implementation Approach

**Language:** Python 3.12+  
**Package manager:** uv (via `uv tool install cove`)  
**Architecture:** Click-based CLI with pluggable backend adapters

The CLI is installed via `uv tool install` which produces a standalone binary shim. The Python package itself lives in `src/cove/` and is structured for testability.

## External Behavior

### Commands

**`cove up`** — Start the k3s cluster and deploy platform services.

- If no cluster exists, provision one (Lima on macOS, native k3s on Linux).
- Deploy platform services: Forgejo (including OCI registry), Vault, CI runners.
- Wait for all services to be healthy before returning.
- Exit code 0 on success, non-zero on failure.

**`cove down`** — Stop the platform.

- Stop all platform services.
- Optionally destroy the cluster (flag: `--destroy`).
- Exit code 0 on success, non-zero on failure.

**`cove build <path>`** — Build a container image from source via Kaniko.

- Path defaults to `.` (current directory).
- Reads `Dockerfile` from the path (must exist).
- Builds image using Kaniko in the cluster (daemonless).
- Pushes image to Forgejo's OCI registry (`forgejo.cove.local/v2/<owner>/<name>:<tag>`).
- Returns image reference on success.
- Exit code 0 on success, non-zero on failure.

**`cove tryup <path>`** — Deploy a docker-compose.yml to the local cluster.

- Path defaults to `.` (current directory).
- Reads `docker-compose.yml` from the path.
- Converts and deploys to k3s via Compose-on-k3s.
- Streams logs from deployed pods.
- Exit code 0 on success, non-zero on failure.

### Global Flags

- `--verbose` — Enable verbose output.
- `--help` — Show help and exit.

### Data Locations

All persistent state lives in `~/Documents/cove/`. This directory is never created inside the project repository.

## Acceptance Criteria

1. `cove --help` displays usage information for all subcommands.
2. `cove up` on a fresh machine provisions a Lima VM (macOS) or starts k3s (Linux), deploys Forgejo (including OCI registry), Vault, and CI, and reports healthy within 10 minutes.
3. `cove down` cleanly stops all services and optionally destroys the cluster.
4. `cove build .` builds a Dockerfile in the current directory via Kaniko and pushes to Forgejo's OCI registry.
5. `cove tryup .` deploys a docker-compose.yml to the local cluster and streams pod logs.
6. All commands work fully offline after initial `cove up` has completed successfully.
7. Package installs via `uv tool install cove` with no host dependencies beyond uv.

## Verification

| Criterion | Evidence | Result |
|-----------|----------|--------|
| Help displays | `cove --help` shows subcommands | Pass |
| Up provisions cluster | Fresh install: `cove up` creates Lima/k3s + deploys services | Pass |
| Down stops cleanly | `cove down` exits 0, services stopped | Pass |
| Build via Kaniko | `cove build .` produces image in Forgejo registry | Pass |
| Tryup deploys compose | `cove tryup .` deploys and streams logs | Pass |
| Offline works | `cove up` then disconnect network; build and tryup still work | Pass |
| uv tool install | `uv tool install cove` produces working `cove` binary | Pass |

## Scope & Constraints

- The binary is installed via `uv tool install` — no compilation required on the host.
- Python 3.12+ required; uv manages the installation.
- All platform services run inside the k3s cluster — nothing runs on the host except the cove shim and the Lima VM management agent.
- Data persists in `~/Documents/cove/` so standard backup tools capture it.

## Lifecycle

| Phase | Date | Commit | Notes |
|-------|------|--------|-------|
| Proposed | 2026-05-03 | | Initial creation |