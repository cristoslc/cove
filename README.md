# Cove

A portable, offline-capable local developer platform running on k3s — a sheltered harbor where code gets built, tested, and deployed before going to sea.

## Vision

Cove gives you a full local dev stack on a single-node k3s cluster. See [docs/vision/](docs/vision/) for the full product vision.

## Services

| Service | Purpose | Notes |
|---------|---------|-------|
| **Forgejo** | Self-hosted Git forge with CI | Runs inside k3s |
| **HashiCorp Vault** | Secrets management | age-encrypted, auto-unseal |
| **CI runners** | Sandboxed build execution | Kata Containers (VM-level isolation) |
| **Local image registry** | Cache images for offline work | `localhost:5000` |
| **Kaniko** | Daemonless container builds | Builds from source without internet |

All services run inside k3s. Nothing new runs on the host.

## Install

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/). Install via:

```bash
uv tool install cove
```

Or install via the Ansible role in the [workstation repo](https://github.com/cristoslc/202604-workstation).

## Quick Start

```bash
cove up           # Start the k3s cluster and deploy platform services
cove down         # Stop the platform
cove build .      # Build a container image from source
cove tryup .      # Try out a docker-compose.yml project on k3s
```

## Platform Requirements

| OS | Runtime |
|---|---|
| macOS | Lima VM (managed automatically) |
| Linux | Native k3s |

## Architecture

All persistent state lives in `~/Documents/cove/`, so existing backup tools capture it automatically.

## Project Artifacts

| Artifact | Status | Description |
|----------|--------|-------------|
| [VISION-001](docs/vision/Proposed/(VISION-001)-Cove-Developer-Platform/(VISION-001)-Cove-Developer-Platform.md) | Active | Cove Developer Platform — full local dev stack vision |
| [EPIC-001](docs/epic/Proposed/(EPIC-001)-Cove-Platform-Core/(EPIC-001)-Cove-Platform-Core.md) | Proposed | Platform Core — cove Python package, k3s, services |
| [SPEC-001](docs/spec/Proposed/(SPEC-001)-Cove-Binary-CLI/(SPEC-001)-Cove-Binary-CLI.md) | Proposed | Cove Binary CLI — up, down, build, tryup commands |
| [ADR-001](docs/adr/Active/(ADR-001)-Python-over-Go-for-Cove-CLI.md) | Active | Decision: Python/uv over Go binary |