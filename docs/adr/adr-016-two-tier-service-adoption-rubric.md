# ADR-016: Two-Tier Service Adoption Rubric

**Status:** Accepted
**Date:** 2026-07-06
**Authored-by:** glm-5.2:cloud
**Supersedes:** ADR-015 (IaaS Graduation Test for Shared Platform Services)
**Trove:** `scheduling-orchestration-iaas@6bab1f8`
**Parley:** `docs/musings/parleys/2026-07-06-dagu-essential-use-case.md`

## Context

ADR-015 established a single test for whether a service qualifies as a shared Cove platform service: a commoditized IaaS contract with a multi-vendor market, enabling endpoint-swap graduation to production. That test correctly gates services like ntfy and MinIO (which pass) and excludes workflow orchestrators like Dagu and Temporal (which fail — no commodity contract, single-vendor formats).

But the parley (`2026-07-06-dagu-essential-use-case.md`) surfaced that Cove has **two purposes**, each with its own test:

1. **Primary: local, offline IaaS.** Provide commodity-contract services so projects can develop against Cove locally and graduate to IaaS by swapping an endpoint URL.
2. **Secondary: developer experience.** Remove per-project setup tax for common categories of work so the operator can test more ideas in a safe harbor and ship the ones that matter. Lock-in is acceptable here *so long as the operator decides the convenience is worth the lock-in*.

ADR-015's test is correct but incomplete — it governs only the primary purpose. A service that fails the IaaS-graduation test is not banned from Cove; it falls into a second tier governed by a different rubric. This ADR defines both tiers and their tests.

## Decision

**Cove services are organized into two tiers, each with its own adoption test.**

### Tier 1 — Core services

Core services are shared platform infrastructure with an IaaS graduation path. They pass the ADR-015 test:

1. **Commodity contract** — the service speaks a vendor-neutral interface (e.g., S3 API, HTTP POST for push).
2. **Multi-vendor market** — multiple independent IaaS vendors accept that contract (not just the same vendor's managed offering).
3. **Endpoint-swap graduation** — a project can develop against Cove locally and swap the endpoint URL to graduate to prod without rewriting integration code.

A service that passes all three runs as a shared instance in Cove's compose stack, consumed by the operator and by user apps at `*.app.cove`. The commodity contract is the anti-rugpull mechanism — if one vendor rugpulls, you swap to another.

**Current core candidates:** ntfy (HTTP push), MinIO (S3 API). Existing core services (Forgejo, Vault, nginx, dnsmasq, dnsproxy) are Cove's own infrastructure, not IaaS-graduation services — they serve Cove itself.

### Tier 2 — Extended services

Extended services fail the Tier 1 test (no commodity contract, no multi-vendor market) but provide developer-experience value that justifies adoption with eyes open about lock-in. The test is multi-factor and weighted, not binary. No single factor is a hard gate; the operator calibrates the weights and draws the line per-service.

#### Factors

| Factor | Weight | What it gates |
|---|---|---|
| **Cost-to-graduate** | Primary | Is there a pricing cliff that traps small/hobby projects, or does graduation cost scale proportionally with use? |
| **Feature parity (self-host vs managed)** | Primary | Does self-host include the features a growing project needs, or are critical features paywalled behind Enterprise licensing? Some gating is acceptable; locking core features behind enterprise licensing is a jump-ship signal. |
| **Exit cost** | Primary | If the vendor rugpulls or prices you out, what does migration cost? Opaque/proprietary formats (e.g., FileMaker) are disqualifying; portable formats (YAML, JSON, code) are fine. |
| **Fork-safety (compound signal)** | Primary | OSI-approved license + community-of-sufficient-size. Either alone is weak; together they're the real anti-rugpull mechanism — the license permits a fork, the community sustains it. "Sufficient size" is smaller in the agentic-coding era but not zero. (OpenTofu/Terraform is the reference example.) |
| **Governance** | Secondary | Foundation governance (ASF, CNCF) is a strong sustainability signal — the foundation owns the trademark and code, multiple companies can offer managed services. Single-vendor governance is higher risk but not disqualifying if other factors compensate. |
| **Community health** | Secondary | Active development, contributor diversity, corporate adoption. Reinforces fork-safety and sustainability. |
| **Foundation path** | Secondary | Has the vendor donated something of meaningful value to a foundation (even if not this specific project)? A signal of commitment to open ecosystems, not a binary gate. |
| **Contributor path** | Secondary (minor) | Is there a documented path for external contributors? Useful but not critical. Community councils are not required. |

#### Calibration notes

- **Cost-to-graduate is the operator's primary red line.** A service that creates a pricing cliff between self-host and managed — where a hobby project that grew can't afford to graduate without rewriting everything — is the canonical failure case (n8n's pattern: self-host is fine until you need RBAC/SSO/version-control, then Enterprise pricing).
- **Fork-safety is compound.** OSI license alone is theoretical; community size alone doesn't help if the license blocks forking. The compound signal is: "if this vendor rugpulls, can the community plausibly sustain a fork?" OpenTofu is the reference: HashiCorp rugpulled Terraform (BSL), the LF took the last MPL version and forked it, the community came with it. A smaller project can still pass if its community is big enough to sustain the fork in the agentic-coding era.
- **No single factor is a hard gate.** A single-vendor project with strong cost-to-graduate, full-featured self-host, portable data formats, and a real community can clear the Tier 2 bar despite lacking foundation governance. The operator decides whether the convenience is worth the residual lock-in risk.
- **Tier 2 services don't get the IaaS-graduation promise.** A project that develops against a Tier 2 Cove service accepts that graduating to prod means either (a) self-hosting the same software elsewhere, or (b) rewriting integration against a different tool. Cove doesn't pretend otherwise.

### What this replaces

ADR-015's test becomes the Tier 1 test specifically. This ADR adds Tier 2 and clarifies that failing Tier 1 doesn't exclude a service — it routes it to the Tier 2 evaluation.

## Rationale

### Why two tiers

Cove's primary purpose is local, offline IaaS — commodity contracts with multi-vendor markets. But its secondary purpose is to improve DX so the operator can test more ideas and ship the ones that matter. A single test (ADR-015) treats these as the same question and loses services that provide real DX value without a commodity contract.

The operator's own framing: "Lock-in is acceptable so long as the operator decides that the convenience is worth the lock-in." That's a judgment call, not a binary gate — and it needs a rubric that surfaces the relevant factors so the judgment is honest.

### Why cost-to-graduate is primary for Tier 2

The operator identified n8n as a personal red line, and on probing, the specific failure was cost: "upgrading to commercial n8n can be cost-prohibitive for a hobby project." n8n's pattern — feature-gate the things a growing project needs (RBAC, SSO, version control), price the managed tier for Enterprise — creates a cliff where a project nurtured in the safe harbor can't afford to ship. That's the failure mode Tier 2 exists to avoid.

Services that pass cost-to-graduate: Dagu (no feature gate, self-host is full-featured, managed tier is optional), Temporal (consumption pricing scales with use, startup credits), Airflow (self-host is full-featured; Astronomer/MWAA/Cloud Composer scale with use), Argo (self-host on K8s; Akuity is optional).

Services that fail cost-to-graduate: n8n (feature cliff + Enterprise pricing).

### Why fork-safety is compound

The operator's reference example: Terraform → OpenTofu. HashiCorp changed Terraform's license to BSL (rugpull); the Linux Foundation took the last MPL-licensed version and forked it as OpenTofu; the community migrated. The fork worked because *both* conditions held: the license permitted it (MPL, OSI-approved) and the community was large enough to sustain it (LF backing, IBM/AWS/corporate users).

A GPL-licensed project with no community is theoretically forkable but practically not — nobody does the maintenance. A large community on a non-OSI license (fair-code, BSL, sustainable use) can't legally fork the last open version. The compound signal is what matters.

### Why governance is secondary, not primary

Foundation governance (ASF, CNCF) is a strong sustainability signal — Airflow, Argo, and DolphinScheduler are foundation-backed with multi-vendor commercial tiers. But the operator explicitly said single-vendor governance is not disqualifying if other factors compensate: "if it were price-competitive enough and had shown sufficient anti-rugpull signals, then I wouldn't necessarily exclude it entirely." Governance is one signal among several, not a gate.

### Why foundation path and contributor path are minor

The operator's calibration: foundation path is "gated on having donated something of meaningful value even if it's not that specific project" — a signal of vendor commitment to open ecosystems, not a binary requirement. Contributor path is "useful, community council isn't critical." These are tiebreakers, not gates.

## Consequences

- **ADR-015 is superseded.** Its test becomes the Tier 1 test specifically. Services that fail it are evaluated under Tier 2.
- **ntfy and MinIO qualify for Tier 1** (core, shared services with IaaS graduation path).
- **No workflow orchestrator qualifies for Tier 1.** Dagu, Temporal, Windmill, Argo, Airflow all fail the commodity-contract test. They route to Tier 2 evaluation.
- **Tier 2 evaluation is per-service and operator-calibrated.** The rubric surfaces factors; the operator weights them and decides. Different operators can draw the line in different places.
- **A service in Tier 2 may be hosted by Cove (as an extended shared service) or shipped as an image for projects to pull (Shape 1).** Which shape applies is a separate question from which tier the service belongs to.
- **The rubric is general** — it applies to any future service candidate, not just schedulers. The factors (cost-to-graduate, feature parity, exit cost, fork-safety, governance, community) are category-independent.

## See also

- ADR-015 — the Tier 1 test (now scoped to core services)
- Trove: `scheduling-orchestration-iaas@6bab1f8` — research on workflow orchestration commoditization
- Parley: `docs/musings/parleys/2026-07-06-dagu-essential-use-case.md` — tensions T1-T8, where this rubric was grilled
- Musing: `docs/musings/windmill-script-scheduler.md` — original Dagu proposal (needs revision against this ADR)