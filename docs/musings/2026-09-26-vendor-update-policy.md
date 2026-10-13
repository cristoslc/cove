# Musing: cove vendor-update policy + registry-driven automation

**Date:** 2026-09-26
**Status:** Proposal (musing → ADR)
**Trigger:** operator — "we need a musing on an automation for cove that defines an update policy (see LiteLLM fiasco earlier this year) and automate the update of vendored components."
**Related:** `docs/musings/litellm-hardening.md` (the fiasco), `docs/musings/2026-09-26-cove-update-command.md` (the consumer of this policy), ADR-015 (IaC graduation test), ADR-016 (two-tier adoption rubric)

## The fiasco, in policy terms

The LiteLLM hardening musing (early 2026) documented a service with **16+ CVEs
and a supply-chain compromise in a single year** — the worst chain CVSS 10.0,
unauthenticated RCE, a CISA KEV listing. Cove's response was excellent
*posture* work: nginx route lockdown, localhost-only, read-only fs, staged
adoption with a 48–72h hold on fresh releases. And it shipped with a quiet,
fatal caveat: **"Upgrade procedure: how to bump the pinned version safely —
to be defined."** It never was.

Eighteen minors later (1.84.0 → 1.102.1 at the time of the staleness audit in
the update musing), the hardening plan's own line — *staged adoption, wait
48–72h after release, review advisories before bumping* — has an execution
gap: nobody's job includes watching BerriAI's advisories, and the pin sits in
three files (`compose/litellm/Dockerfile`, `compose/litellm/docker-compose.yml`,
`bringup.yml`) that can drift from each other. The forging incident is
instructive precisely because it shows both halves of the pattern we keep
repeating:

1. **We pin** (correct — pinned, never floating),
2. **and then nothing** watches the pin for staleness, nothing owns the
   refresh, and the "wait 48h and review advisories" discipline lives in a
   musing instead of a machine.

The Forgejo-15-behind-16 finding from the same audit is the same story in
the slow lane: no CVE, just decay.

## What "vendored" means in cove

Cove vendors upstream software as a product decision (ADR-016: opinionated,
one answer per service). That makes cove the vendor of record for everything
it ships — the operator's exposure to upstream incidents is mediated entirely
by cove's update pipeline. The inventory today (2026-09-26):

| Component | Pin surface(s) | Upstream feed |
|---|---|---|
| Forgejo | `codeberg.org/forgejo/forgejo:15` (group_vars) | codeberg releases |
| Vault | `1.20` + **digest** (group_vars) | hashicorp releases |
| nginx | `nginx:1.27-alpine` (group_vars) | docker hub |
| LiteLLM | `cove-litellm:1.84.0` custom Docker build (`pip install litellm[proxy]==1.84.0` in the Dockerfile) | **pypi** (BerriAI) |
| Headroom | `ghcr.io/...@sha256:<digest>` | ghcr digest |
| Speedtest | `v1.14.5-ls162` (bringup default) | linuxserver releases |
| bb-app | `0.44.0` (compose args + Dockerfile ARG) | npm |
| Python deps | `cryptography>=50.0.0` (pyproject floor) | pypi advisory DB |

Three structural problems fall out of this table:

1. **No registry.** Pins live in four different formats across six files.
   Discovering "what do we vendor and how stale is it" means grepping. There
   is no artifact a machine can consume, so nothing can automate it.
2. **No policy.** The litellm plan's staged-adoption rule (48–72h hold,
   advisory review) was written down but never became a *procedure* — it
   lives in prose, applies to one service, and has no owner, cadence, or
   trigger. Forgejo 16 sitting unadopted is the same policy failure in the
   slow lane.
3. **Custom builds rot invisibly.** `cove-litellm:1.84.0` is built from
   `pip install litellm[proxy]==1.84.0` — the real pin is inside a Dockerfile,
   invisible to any image-tag-based staleness check.

## Proposal

### 1. `compose/vendor.yaml` — one machine-readable registry

Every vendored component declared once:

```yaml
components:
  litellm:
    kind: pypi
    package: litellm[proxy]
    current: "1.84.0"
    build: compose/litellm        # cove builds it; wheel pin lives here
    hardening: docs/plans/litellm-hardening.md   # standing constraints
  forgejo:
    kind: codeberg-release
    repo: forgejo/forgejo
    current: "15"
    majors: scheduled-session     # migration-bearing
  bb-app:
    kind: npm
    package: bb-app
    current: "0.44.0"
  headroom:
    kind: digest
    registry: ghcr.io/chopratejas/headroom
    current: "sha256:50b8..."
    staged-adoption-days: 3       # litellm-hardening rule, made mechanical
```

Tests (the parity pattern from the cert-SAN drift fix) validate that the pins
in compose/bringup/Dockerfiles **match the registry** — a pin that exists
outside the registry fails the gate, so the registry cannot silently rot.

### 2. The policy, as enforceable statements

- **Security SLA:** a CVE with network reachability (given cove's per-service
  threat model — localhost-only, nginx-fronted) in a vendored component gets
  an expedited cove release; target: **72 hours from advisory to wheel**.
  CISA KEV listings are always expedited. The staged-adoption window
  (48–72h soak on fresh releases, from litellm-hardening §3) is *suspended*
  for security fixes and *enforced* for feature bumps.
- **Freshness SLO per tier** (static in the registry, not per-decision):
  bb-app/litellm-class: updated when upstream ships, weekly check minimum.
  Forgejo: majors land within one release cycle (~30 days) via a scheduled
  operator session. Digest-pinned images: re-pinned on advisory or quarterly.
- **Every exception is written down where the pin is** — a component that
  can't be auto-bumped (vault unseal, forgejo major) carries its migration
  procedure next to its registry entry, so the busywork has a procedure
  attached when it finally runs.

### 3. The automation

- **Repo-side watcher** (CI, scheduled): queries each feed, diffs against the
  registry, opens an automated bump PR per component (cove's own
  Dependabot-style flow, which has precedent — the cryptography CVE bump).
  PR body carries the advisory/diff; security PRs flagged for expedite.
- **`cove update --check`** (already in PR #58) reads the same registry, so
  operator-side staleness reporting and repo-side bump automation share one
  inventory instead of two drifting ones.
- On merge + promote, `cove update` ships it fleet-wide — the
  vendor-update-command musing's daily loop is the *consumer* of this policy;
  this musing defines the *supply* side: how bumps get authored, gated, and
  how fast they must move.

### Why a registry and not just more Renovate config

Renovate/Dependabot watch *files*; cove's pins are already split across
formats, and the important relationships (litellm pin ↔ headroom compat,
forgejo major ↔ migration session, bb-app ↔ host-daemon tarball anchor) are
knowledge, not version strings. The registry is where the pin lives *with*
its policy metadata — feeds, SLOs, migration procedures, staged-adoption
flags. The bump PRs and `cove update --check` both consume it. One inventory,
two consumers, no drift.

### The litellm fiasco's lesson, stated as policy

The hardening musing's checklist was thorough on *posture* (isolation,
route lockdown, hash pinning) and silent on *cadence*. Pinning 1.84.0 was the
right call at the time — and it fixed a CVSS-10 chain — but "pin" is a
moment, not a state. The policy closes the loop: **the moment of pinning
must include the moment of unpinning** (feed, SLA, and the automation that
notices when the unpinning is due). Staged adoption for feature releases
stays: it is cheap, and litellm's supply-chain history is why.

## Open questions

- Registry format and location (`compose/vendor.yaml` vs pyproject section).
- Does the watcher auto-merge `float`-within-major bumps for **cove's own
  wheel** (deps like `cryptography`) while gating everything else on CI?
- Who reviews security-adjacent bumps when the operator is the only human —
  the answer is probably "CI + the staleness report *is* the review," with
  the 72-hour SLA as the commitment, not the mechanism.
- Forgejo major bumps: scheduled-session checklist (backup, migration notes,
  rollback image kept) — write the runbook when the first major bump is
  attempted (16 will be the first).
