---
title: "Python over Go for Cove CLI"
artifact: ADR-001
track: standing
status: Active
author: cristos
created: 2026-05-03
last-updated: 2026-05-03
depends-on-artifacts: []
evidence-pool: ""
---

# Python over Go for Cove CLI

## Status

Active

## Context

Cove needs a CLI tool that developers install on their workstations. The tool must manage k3s clusters, deploy services, and build container images. Two implementation candidates were on the table:

1. **Go** — compiled binary, single `curl | install` command, fast execution, no runtime needed.
2. **Python** — installed via `uv tool install`, requires Python 3.12+ on the host.

Go was initially explored. A `cove` binary existed in the repository with a `.goreleaser.yml` for cross-platform releases. However, maintaining Go toolchains across different environments and managing cross-compilation for release artifacts added complexity that conflicted with the maintenance budget constraint.

## Decision

Cove will be implemented in Python 3.12+ and distributed via `uv tool install cove`.

## Rationale

uv produces a standalone binary shim that wraps the Python package. From the user's perspective, installation is a single command with no compilation step and no need to manage a Go toolchain. The shim behaves identically to a compiled binary — no Python interpreter knowledge required at install time.

Python's ecosystem provides first-class libraries for every subsystem Cove needs: Click for CLI composition, PyYAML for Kubernetes manifests, kubernetes-client for k8s API calls, and paramiko or subprocess for Lima/k3s provisioning. Go would require equivalent libraries but with a heavier cross-compilation burden for releases.

One person can maintain a Python package more easily than a Go project with multi-platform release engineering. The uv distribution model closes the gap between Python's flexibility and Go's installation simplicity.

## Alternatives Considered

### Go

Go produces a true static binary with no runtime dependencies. The initial `cove` prototype used Go. However, `goreleaser` cross-compilation for macOS/Linux/arm64/amd64 requires a CI pipeline or manual tooling. Bug fixes require a full release cycle. Python with uv allows in-place updates via `uv tool upgrade cove` with no platform-specific build artifacts.

### Shell scripts

Bash or Python scripts invoked directly lack the structured CLI interface (subcommands, flags, help) that makes a tool approachable. Shell scripts also have cross-platform portability issues between zsh/bash/fish.

## Consequences

- **Positive**: Single-command install via `uv tool install`. No cross-compilation pipeline. In-place upgrades. Rich Python library ecosystem.
- **Negative**: Requires Python 3.12+ on the host (mitigated: uv installs Python automatically if missing).
- **Negative**: Python startup overhead (~100ms) vs Go's near-zero startup (acceptable for a CLI that performs network I/O).

## Lifecycle

| Phase | Date | Commit | Notes |
|-------|------|--------|-------|
| Active | 2026-05-03 | | Adopted — Python/uv replaces Go binary direction |