# Parley: Dagu — Essential Use Case

**Date:** 2026-07-06
**Topic:** What is the essential use case for scheduling in Cove, and what does it imply for where Dagu lives?

**Opening position (operator):** The essential use case originated in Project Hal — a Cove consumer that needed scheduling to run. Research pipeline projects would also benefit. Those pipelines need to run with their own project + associated tooling in place, on a per-project instance, not a single cove-wide instance.

**Prior parley:** `2026-07-06-dagu-revision.md` is set aside. It was built on the assumption that Dagu is cove-wide platform infrastructure. The operator is re-examining from the use case outward.

## Tension backlog

### T1 — Per-project vs cove-wide (resolved)

Two shapes for where Dagu lives:
1. **Shape 1 (image library)** — Cove provides images for common project problems. Project Hal's compose stack includes a `dagu` service built from `cove-dagu` image. Dagu runs *as part of Hal*, with Hal's repo mounted, Hal's tools present. The container-within-container problem dissolves.
2. **Shape 2 (shared multi-tenant)** — Cove hosts a running instance. Projects point at it.

The essential use case ("per-project, with project tooling") only fits Shape 1. Shape 2 reintroduces the container-within-container problem the prior parley killed.

**Resolution:** Shape 1 for Dagu. Shape 2 fits services decoupled from consumer runtime (ntfy, MinIO).

### T2 — Two tests, not one (resolved)

The operator surfaced that Cove has two purposes, each with its own test for "should Cove provide this":

1. **Primary: local, offline IaaS.** Test: IaaS graduation (ADR-015) — commodity contract + multi-vendor market + endpoint swap. ntfy and MinIO pass. No workflow orchestrator passes.
2. **Secondary: improve DX so the operator can test more ideas in a safe harbor and ship the ones that matter.** Test: TBD. Lock-in is acceptable here *so long as the operator decides the convenience is worth the lock-in*. Different operators draw the line differently.

ADR-015's essential test is the difference between "core" Cove services (pass the IaaS graduation test) and "extended" Cove services (fail the IaaS test but pass the DX test). ADR-015 needs to be superseded by a more nuanced rubric that captures both tiers.

**Resolution:** ADR-015 stays as the test for the *core* tier. A new rubric (ADR-016, forthcoming) defines the *extended* tier: when is lock-in acceptable for DX? Factors: rugpull risk, pricing, sustainability, governance, community, exit cost.

### T3 — Scheduling fails the core test, what about the extended test? (open)

No workflow orchestrator has an IaaS-graduation path. But the operator's DX need is real: "I have a project that needs to run something on a schedule, and I don't want to think about HOW — I just want to do it with a nice monitoring and log review dashboard."

Two candidate answers for the extended tier:
- (a) Cove ships a `cove-dagu` image (Shape 1); the operator pulls it into projects that want the DX, eyes open about lock-in.
- (b) Cove hosts Dagu as an extended service; the operator accepts the lock-in for the dashboard DX; per-project still wins because DAGs can mount project repos? (TBD — needs investigation of how Dagu handles multiple projects/repositories from a single instance.)

### T4 — Apache/CNCF governance as a sustainability signal (open)

The operator asked specifically about Apache Foundation or CNCF projects with commercial-tier support for scheduling. Findings:

| Project | Foundation | Maturity | Commercial tier | Governance |
|---|---|---|---|---|
| Apache Airflow | ASF | Top-level (2019) | Astronomer (managed), AWS MWAA, GCP Cloud Composer | Foundation — multi-vendor, no single company controls |
| Argo Workflows | CNCF | Graduated (2022) | Akuity, Codefresh | Foundation — multi-vendor |
| Apache DolphinScheduler | ASF | Top-level | WhaleStudio (WhaleOps) | Foundation — multi-vendor |
| Temporal | None (Temporal Technologies, Inc.) | N/A — single-vendor | Temporal Cloud | Single company. Joined AAIF (Linux Foundation) as Gold Member Dec 2025, but the *project* is still owned by Temporal Technologies. Not donated to a foundation. |
| Dagu | None (dagucloud) | N/A — single-vendor | Managed Dagu | Single company. No foundation involvement. No published governance model. |

**Key finding:** Airflow, Argo, and DolphinScheduler have foundation governance with a multi-vendor commercial tier — the foundation owns the trademark and code, multiple companies offer managed services. Temporal and Dagu are single-company-owned — the same company that sells the managed service owns the project. A rugpull (license change, project abandonment, hostile monetization) is structurally possible for Temporal/Dagu in a way it isn't for Airflow/Argo.

**This is a strong sustainability signal but not a hard gate.** The operator may decide a single-vendor project is worth the lock-in for its DX advantages. The rubric should weigh foundation governance as a major factor, not a binary requirement.

### T5 — What is the "extended" rubric? (open)

The operator named factors: rugpull, pricing, sustainability, governance, and a host of others. The rubric needs to capture:

- **Rugpull risk** — can the vendor change the license, close the source, or hostile-monetize? Foundation governance mitigates; single-vendor is higher risk.
- **Pricing** — is the managed/cloud tier priced such that graduation is plausible, or is it priced to trap? (Temporal Cloud's consumption pricing starts low but scales; Astronomer is enterprise-priced; Dagu managed pricing not published.)
- **Sustainability** — is the project healthy? Commit velocity, contributor diversity, corporate sponsors, foundation maturity level.
- **Governance** — foundation (ASF/CNCF) vs single-vendor vs BDFL.
- **Exit cost** — if Cove adopts this and the vendor rugpulls, what is the cost to migrate off? Rewriting DAGs in a different format is high; rewriting cron expressions is low.
- **Lock-in surface area** — what exactly gets locked in? Data (in their DB)? Configuration (in their format)? Both? Dagu is file-backed and YAML — the lock-in surface is the DAG format, not the data. Temporal's lock-in is event-history in their DB plus code in their SDK.

**Open question:** is this rubric a Cove-specific operator judgment (where *I* draw the line), or a portable framework other operators could apply? The operator's framing ("for cove, it's largely about where I draw the line") suggests Cove-specific — but the *factors* are general; only the *thresholds* are operator-specific. Worth probing.

### T6 — n8n as the negative example (open)

The operator cited "n8n-level lock-in" as a personal red line. Worth pinning down what specifically about n8n constitutes unacceptable lock-in, to calibrate the rubric's thresholds. Hypothesis: n8n's lock-in is (a) visual workflow format with no portable text representation, (b) Fair-code license (not OSI-approved), (c) single-vendor with no foundation path. Dagu shares (c) but not (a) or (b). Where does the operator's line actually fall?

### T7 — Dagu under the Tier 2 rubric (resolved)

Applying ADR-016 to Dagu:

| Factor | Dagu's profile | Assessment |
|---|---|---|
| **Cost-to-graduate** | Self-hosted Dagu is the *full* feature set — RBAC, SSO, OIDC, API keys, audit logs all in the GPLv3 binary. No feature gate between self-host and cloud. Managed Dagu (gVisor on GKE) is optional. If Dagu Cloud gets expensive, you keep running the same binary on your own infra. | **Passes.** No pricing cliff. |
| **Feature parity** | Self-host = full features. No "Community Edition" paywalling. | **Passes strongly.** |
| **Exit cost** | DAGs are YAML, file-backed. State is JSON files. No DB. Migration cost = rewriting YAML in a different format (lower than Temporal's code+DB migration; higher than cron's crontab line). Not an opaque/proprietary format. | **Passes.** |
| **Fork-safety (compound)** | GPLv3 (OSI-approved). Community is active but small — single company (dagucloud), no published contributor diversity numbers. Recent v1.x releases with active development. The agentic-coding era lowers the maintenance tax for a fork, but the community is small enough that a fork's sustainability is uncertain. | **Passes weakly.** The license permits a fork; the community is big enough to *plausibly* sustain one but not clearly big enough to guarantee it. This is Dagu's weakest signal. |
| **Governance** | Single-vendor (dagucloud). No foundation involvement. No published governance model. | **Weak — secondary factor, not disqualifying.** |
| **Community health** | Active development, recent releases, but small community compared to Airflow/Argo. No corporate users publicly listed. | **Moderate.** |
| **Foundation path** | dagucloud has not donated anything to a foundation. | **Fails — minor factor.** |
| **Contributor path** | No published governance/contributor model. | **Fails — minor factor.** |

**Verdict:** Dagu clears the Tier 2 bar. The primary factors (cost-to-graduate, feature parity, exit cost) all pass. Fork-safety passes weakly — the GPLv3 is solid, the community is the question mark, but the agentic-coding era lowers the threshold and the community is active if small. The secondary factors (governance, foundation path, contributor path) are weak but not disqualifying per the rubric — the operator explicitly said single-vendor governance is acceptable if other factors compensate.

The residual risk is sustainability: if dagucloud abandons the project, a fork depends on community capacity that exists but isn't large. Mitigation: the exit cost is low (YAML DAGs, file-backed state, no DB), so even a worst-case rugpull is a migration to a different tool, not a data-extraction crisis.

### T8 — Shape 1 vs Shape 2 for Dagu in Tier 2 (open)

Dagu clears Tier 2, but the shape question (T1) is still open. The essential use case is per-project ("runs with the project's own tooling"). A single Cove-hosted Dagu instance serving multiple projects would need all project directories mounted into the Dagu container — a scope/blast-radius question.

Two options:
- **(a) Shape 1 — Cove ships a `cove-dagu` image.** Projects that want the dashboard DX pull it into their own compose stack, with their own repo mounted. No Cove-hosted instance. Lock-in is per-project and opt-in.
- **(b) Shape 2 — Cove hosts a Dagu instance as an extended service.** DAGs for multiple projects coexist, each with `working_dir` pointing at a mounted project path. The dashboard is shared. But: the Dagu container has access to all project paths, and a misconfigured DAG could touch another project's files.

The parley record flagged this as blocked on T5/T6; those are now resolved (ADR-016). The remaining question is whether the operator wants a shared dashboard (Shape 2, one place to see all scheduled jobs across projects) or per-project dashboards (Shape 1, each project's Dagu is isolated).

## Record

- T1-T2 resolved early in this parley session.
- T3-T6 resolved through ADR-016 (the two-tier rubric) and the fork-safety compound-signal calibration.
- T7 resolved: Dagu clears the Tier 2 bar. Primary factors pass; fork-safety passes weakly (GPLv3 solid, community is the question mark but agentic-coding era lowers the threshold); secondary factors weak but not disqualifying.
- T8 open: Shape 1 (cove-dagu image, per-project) vs Shape 2 (Cove-hosted instance, shared dashboard). Blocked on operator preference for shared vs per-project dashboard UX.
- ADR-015 superseded by ADR-016 (`a58b380`).