# ADR-018: ADE — Agentic Development Environment (bb as default harness)

**Status:** Accepted
**Date:** 2026-09-25
**Accepted:** 2026-09-25 (operator instructed implementation; acceptance implied by go)
**Authored-by:** glm-5.3-flash (opencode inside bb)
**Musing:** `docs/musings/2026-09-24-bb-harness-in-cove.md`
**Related:** PURPOSE.md (Low-Isolation, Low-Friction by Default), ADR-016

## Context

Cove's purpose docs say Cove is infrastructure, not a development environment — but that bullet conflated two different things: *tools that edit code* (editors, LSPs, language runtimes) and *the layer agents execute in*. An agentic development environment (ADE) that integrates with any agent harness is harness-agnostic infrastructure, and infrastructure is exactly what Cove ships. The operator's decision: **the ADE ships as part of Cove, with bb as the default harness — the way Vault is the default vault and Forgejo the default forge.**

The harness-catalog trove (`docs/troves/harness-catalog/`) originally planned an `opencode.cove` web surface; bb superseded it by providing the orchestration surface itself. Parley decisions: bb lives with cove, ingress via cove's nginx replaces dependence on the getbb.app relay, and isolation follows the PURPOSE principle (Low-Isolation, Low-Friction by Default) — a step-up you choose, never a forced container.

## Decision

**Cove ships an ADE as a first-class service category. bb is its default harness.** The ADE's execution modes are features of the ADE, orthogonal to service bundles.

### 1. Harness-agnostic ADE, bb as the default instance

The ADE is defined by its role — the layer where coding agents execute — not by bb. bb is the first implementation, chosen the way every Cove default is chosen: opinionated, one answer, no assembly required. Adding or swapping a harness later is an implementation concern behind the ADE surface. What Cove commits to is the integration shape (below), which any harness can fill.

### 2. Execution modes are features, available at every tier

The ADE's three execution modes — host (default), containerized machine (step-up), per-project container (step-up, narrower scope) — are ADE features, not gated by service bundles. Activation bundles describe *which services* a Cove instance runs (litellm would be an advanced example), not which features exist. A minimal instance still gets host execution and can step up to a container on demand. Bundle design is a separate proposal: ADR-019.

### 3. Integration shape (the bb instance today)

bb's own seam — one server, many machines — maps onto the harbor directly:

1. **bb-server is a compose service.** Stateful container on the cove network; SQLite + data-dir under `~/Documents/cove-data/` (Data in Documents); no direct host ports beyond the mapped loopback port for the Mac's desktop app.
2. **The host is enrolled as machine #1 — the day-one state.** The bb host daemon already runs on the Mac; enrolling it to the containerized server is free and preserves continuity: existing projects, threads, and worktree paths keep working. This is the low-isolation default on purpose. The host is the operator's own device; cove does not govern it, and the ADE never requires a container around the operator's own work.
3. **Ingress: `ade.cove`.** nginx site in `default.conf.j2`, mkcert TLS, serving the bb web UI to browser and phone over Direct URL mode. The getbb.app relay is not replicated; bb Connect remains an optional operator choice for push/universal links.
4. **Enrollment is the unit of scale.** `cove ade up` provisions a machine container (profiled service, Forgejo-runner shape): daemon inside, enrolled to the server over the cove network, projects cloned from `git.cove` (dnsmasq reachable, mkcert CA in the image trust store). Machine #2 takes the identical path machine #1 took. A future per-project harness mode reuses the same enrollment, scoped narrower. No step introduces a new architecture.

### What is deliberately not here

- **No isolation tiers.** Sensitivity is per-project and momentary, encoded in which execution environment a task runs on — not in standing labels. (Per-project scoping precedent: `mcp-isolation-and-dynamic-mounts.md`.)
- **No group-isolation primitive.** Deferred until a real multi-repo group exists; per-project containers on one compose network already compose into a group ad hoc.
- **Provider-auth mechanics.** Subscription logins in persistent volumes (pets) vs API keys from Vault via `cove creds` (cattle, metered billing) — per-provider decision at implementation time.

## Consequences

- PURPOSE.md is amended: "What Cove Is Not" narrows to *code editor* (editors/LSPs/runtimes stay out). The ADE-as-core-service stance supersedes the old "no coding harnesses" exclusion.
- The loopback problem dissolves: the server lives on the cove network, so machine containers reach it directly; only the Mac needs the mapped port.
- The musing's earlier "containerized-only" stance is superseded by the PURPOSE principle: host execution is the default, containers are the step-up.

## Open questions (spike list)

> **Spike update (2026-09-25):** Q1 and Q4 are de-risked by documented bb mechanisms (verified via `bb guide machines` / `bb guide agent-configuration`):
> - **Q1 — enrollment:** first-class. `bb settings general machineServerUrl <url>` sets the reachable server URL; `bb settings general defaultMachineAccess direct|connect` picks the access provider; `bb machine enroll --bootstrap-file <path>` gives scripted, IaC-shaped enrollment. A Tailscale plugin can supply private access instead of a Direct URL. Works in principle over the cove network (`http://bb:<port>`); live verification is the remaining step. bb also clones the project's Git remote onto the connected machine itself, so "clone from git.cove" is native behavior, not custom wiring.
> - **Q4 — data dir:** bb reads config and state from a configurable `<dataDir>` (default `~/.bb`). Mount a volume and point the container at it; the exact env var/property is the only remaining detail.
>
> Q2 (provider CLI logins in volumes) and Q3 (web/mobile behind nginx) remain open and gate the containerized-machine rung.

1. Does the bb host daemon enroll over plain HTTP inside the cove network, or does it demand the server's public URL shape? (Gates runner-style scripted enrollment.)
2. Do provider CLIs (Claude Code, Codex, OpenCode, Pi) tolerate volume-persisted logins across container restarts?
3. Does the web/mobile client work against the compose-hosted server behind nginx — websockets, headers, pairing over Direct URL?
4. Where does bb's data-dir convention land in containers (`BB_DATA_DIR`/XDG) so thread state survives image upgrades?

## Phase 1 implementation note (2026-09-25)

Phase 1 shipped a second bb server as an optional `ade` compose profile with an
`ade.cove` nginx site, a `cove ade` CLI, and tests. Three spikes de-risked it:
`--server-bind-host 0.0.0.0` binds wildcard with no Connect; `/ws` upgrades
through nginx with standard headers; a pinned `bb-app` starts headless and
serves `/health`.

Two points deserve ADR-level record because they are security-shaped:

- **Direct-URL mode carries no application auth.** bb documents wildcard
  binding as security-sensitive; the public API permits command execution and
  file reads. The ingress therefore **enforces** the trust boundary rather
  than assuming it: the `ade.cove` location allows private-range clients
  (loopback, container ranges `172.16.0.0/12`, LAN `10/8` + `192.168.0.0/16`,
  tailnet CGNAT `100.64.0.0/10` — the latter two widened by operator decision
  2026-09-25) and denies public-internet sources. Ingress auth is a planned
  addition; until then the private-range boundary is the control. Widening
  beyond private ranges is an explicit operator decision, not a default.
- **One port source of truth.** `ADE_PORT` threads through compose env, the
  container healthcheck, and the nginx upstream; the container is addressed by
  the stable service alias `ade`, so a `container_name` override cannot
  silently break the proxy.

Host enrollment and live-server cutover remain Phase 2.

## See also

- PURPOSE.md — Low-Isolation, Low-Friction by Default
- Musing: `docs/musings/2026-09-24-bb-harness-in-cove.md` — full decision thread, ADR-016 scorecard, auth trade-offs
- ADR-016 — Two-Tier Service Adoption Rubric
- `docs/musings/mcp-isolation-and-dynamic-mounts.md` — per-project scoping precedent, `cove project` surface
