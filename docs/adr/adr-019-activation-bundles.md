# ADR-019: Activation Bundles for `cove up`

**Status:** Proposed
**Date:** 2026-09-25
**Authored-by:** glm-5.3-flash (opencode inside bb)
**Related:** PURPOSE.md (Low-Isolation, Low-Friction by Default), ADR-016, ADR-018

## Context

`cove up` activates one fixed service set today. As Cove's service catalog grows — optional profiles like litellm, speedtest, and the Forgejo runner, plus the ADE from ADR-018 — every new service adds a decision at init and a question at upgrade ("do you want this too?"). A flat list turns Cove's front door into a configuration maze, which is the toll booth the Low-Friction principle says gets routed around.

The init and upgrade moment needs a way to express posture, not a per-service questionnaire.

## Decision

**`cove up` offers three activation bundles — minimal, comfortable, advanced — on first init and on upgrades that introduce new services. Bundles decide which services activate; they never gate features.**

### The bundles

| Bundle | Character | Covers |
|---|---|---|
| **Minimal** | The original harbor | forge (Forgejo), vault, CI runner, registry, pages, observability |
| **Comfortable** | Adds developer-experience convenience, no new decisions | minimal + DX tooling; first known member: the ADE (bb, ADR-018) |
| **Advanced** | Adds optional tooling that raises configuration weight and decision load | comfortable + litellm and comparable services; nothing here is needed until you know you need it |

Membership is provisional and calibrates over time. The placement test is **decision load**, not importance or sophistication.

### Rule 1: bundles gate services, not features

A bundle describes what runs on the instance. It does not describe what Cove can do. Features — the ADE's host/container/per-project execution modes (ADR-018), per-project scoping, isolation step-ups — are available on every bundle, including minimal. A minimal instance is small, not crippled. Gating a feature behind a bundle would make bundles a capability paywall, which they are not.

### Rule 2: bundle movement is cheap and non-destructive

The bundle is a posture, not a commitment. Moving up adds services; moving down stops services without destroying their data (data dirs persist, per Data in Documents). One command. No init choice should feel like a trap.

### Rule 3: upgrades propose, they do not force

When an upgrade introduces a service outside the active bundle, `cove up` surfaces a bundle-move prompt rather than silently adding or dropping it. (Mechanics TBD — see open questions.)

## Rationale

- **Front-door friction is the failure mode.** Each added service question compounds at init; bundles collapse N questions into one posture choice.
- **The ADE forced the issue.** Shipping bb as a default means Cove now activates developer-experience tooling, which changes the character of the default instance. Bundles make that change explicit instead of silent.
- **Decision load is the right axis.** Minimal vs advanced is not "basic vs powerful"; it is "few decisions vs many." A service with sane defaults that needs no configuration does not belong in advanced merely because it is sophisticated.

## Consequences

- `cove up` gains a bundle surface on init and upgrade. The instance records its active bundle; later ups respect it.
- Services need declared bundle membership in their bringup/compose metadata.
- ADR-018's ADE integrates as a comfortable-bundle service.
- Existing installs need a default mapping (current service set → minimal, or → comfortable). TBD.
- The profiles mechanism (`cove litellm`, `cove runner`, `cove speedtest` today) is not replaced; bundles compose on top of it.

## Open questions

1. **Presentation mechanics:** flag (`--bundle comfortable`), interactive prompt with a default, or both?
2. **Upgrade prompting:** how does `cove up` detect a new service outside the active bundle, and how loud is the prompt?
3. **Existing-install default:** do current installs map to minimal or comfortable, and what happens to already-running optional profiles?
4. **Mixing:** can an instance sit on comfortable but opt into litellm individually, or is litellm reachable only by moving to advanced?
5. **Where bundle membership lives:** bringup.yml, per-service manifest, or a central catalog?
6. **Downgrade:** does moving down warn about which services it would stop?

## See also

- PURPOSE.md — Low-Isolation, Low-Friction by Default
- ADR-018 — ADE: Agentic Development Environment (bb), the first comfortable-bundle member
- ADR-016 — Two-Tier Service Adoption Rubric (what runs in Cove at all)
- Existing optional profiles: `cove litellm`, `cove runner`, `cove speedtest`
