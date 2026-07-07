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

### T7 — Dagu specifically under the extended rubric (open, blocked on T5/T6)

Once the rubric exists, Dagu gets evaluated:
- **Rugpull:** single-vendor (dagucloud), GPLv3, no foundation. Higher risk than Airflow/Argo.
- **Pricing:** managed Dagu exists but pricing not public; the project's "thousands of runs per day on one machine" positioning means self-hosting is viable at small scale.
- **Sustainability:** active development, recent v1.x releases, but small community compared to Airflow/Argo. No published governance model. Single maintainer/company.
- **Governance:** single-vendor. No foundation path.
- **Exit cost:** DAGs are YAML, file-backed. Exit cost = rewriting YAML in a different format. Lower than Temporal (rewrite code + migrate DB) but higher than cron (rewrite crontab line).
- **Lock-in surface:** the DAG format. State is file-backed JSON, exportable. Not data lock-in.

Dagu's profile under the rubric: single-vendor governance (red flag for sustainability), but low exit cost (YAML DAGs, file-backed state, no DB lock-in). Whether the operator accepts this trade is the open question.

### T8 — Should Cove host Dagu at all, even as extended? (open, blocked on T3)

If the essential use case is per-project (T1 resolved Shape 1), then Cove hosting a Dagu instance — even as an extended service — may not fit. The question is whether a single Dagu instance can serve multiple projects with their own tooling/repositories, or whether per-project Dagu is structurally required.

Dagu's execution model: DAGs run shell commands as subprocesses of the Dagu process, with the DAG's `working_dir`. A single Dagu instance *could* run DAGs for multiple projects if each DAG sets its `working_dir` to the project's path — but only if the Dagu container has access to all those project paths. In a Docker-in-Cove model, that means mounting all project directories into the Dagu container, which is a scope/blast-radius question.

This tension is deferred until T5/T6 resolve (what the rubric says about Dagu) and then re-examines whether hosting fits.

## Record

- T1-T2 resolved in this parley session.
- T3-T8 open.
- ADR-015 recorded the IaaS graduation test for the *core* tier.
- A new ADR (ADR-016) will supersede/refine ADR-015 to capture both tiers once the extended rubric is grillable.