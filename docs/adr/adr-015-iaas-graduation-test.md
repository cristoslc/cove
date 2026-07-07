# ADR-015: IaaS Graduation Test for Shared Platform Services

**Status:** Accepted
**Date:** 2026-07-06
**Authored-by:** glm-5.2:cloud
**Trove:** `scheduling-orchestration-iaas@6bab1f8`

## Context

Cove is a local developer platform. It provides shared infrastructure services (Forgejo, Vault, nginx, dnsmasq, dnsproxy) and is considering adding more (scheduling, object storage, notifications).

A recurring question: which services should Cove host as shared platform services (a single instance running in Cove's compose stack, consumed by the operator and by user apps at `*.app.cove`), versus which should Cove ship as images/building blocks that projects pull into their own stacks?

The distinction matters because shared services carry an implicit promise: **develop against Cove locally, graduate to IaaS in production by swapping the endpoint.** That promise is the entire value proposition of a shared Cove service. If a project develops against a Cove-hosted service and then has to rewrite its integration to move to prod, Cove has created lock-in rather than affordance.

## Decision

**A service qualifies as a shared Cove platform service (Shape 2) only if its contract is commoditized at the IaaS layer — meaning multiple independent vendors accept the same interface, so a project can swap the endpoint URL and move to prod without rewriting integration code.**

The test:

1. **Is there a commodity contract?** (e.g., S3 API for object storage, HTTP POST for push notifications)
2. **Does a multi-vendor market accept that contract?** (multiple IaaS providers, not just the same vendor's managed offering)
3. **Can a project swap the endpoint URL and graduate to prod without code changes?**

If all three hold → shared platform service (Shape 2). Cove hosts it, projects develop against it, swap endpoint for prod.

If any fail → not a shared service. Cove may still ship an image or building block (Shape 1) that projects pull into their own stacks, but Cove does not host a running instance as platform infrastructure.

## Rationale

### Why this test

ntfy and MinIO pass the test cleanly:
- **ntfy** — HTTP POST to topic. Vendors: SES, FCM, APNs, Pushover, Pushbullet, SNS. Swap endpoint, change auth, done.
- **MinIO** — S3 API. Vendors: AWS S3, Cloudflare R2, Backblaze B2, Wasabi, DigitalOcean Spaces, Azure (via S3-compatible API). Swap endpoint, done.

These services earn their place as shared Cove infrastructure because the affordance they provide is real: develop locally against `notify.cove` / `s3.cove`, swap to SES / R2 in prod.

### What fails the test

Workflow scheduling/orchestration fails. The trove `scheduling-orchestration-iaas@6bab1f8` found:

- Every orchestrator speaks a product-specific format (Dagu YAML, Temporal Workflows-as-Code, Argo YAML, Airflow DAGs, AWS ASL, Azure Logic App JSON, GCP Workflows YAML).
- The "managed cloud" of each is just the same vendor hosting their own format. Dagu Cloud runs Dagu. Temporal Cloud runs Temporal. There is no multi-vendor market for any workflow DSL.
- Standardization attempts (CNCF Serverless Workflow DSL, OASIS TOSCA) exist as specifications but have not produced a hyperscaler-accepted commodity contract. Synapse/SonataFlow are reference runtimes, not a market.
- The only commoditized scheduling primitive is **cron syntax at the trigger layer**, and the only cross-vendor-portable compute target is **Kubernetes CronJob** (because K8s itself is the commodity).

So no workflow orchestrator qualifies as a shared Cove platform service under this test. Dagu, Temporal, Windmill, Argo, Airflow — all are product lock-in choices. Cove may ship any of them as an image (Shape 1), but should not host one as shared infrastructure with the implicit "swap to IaaS in prod" promise, because that promise cannot be kept.

### Why this matters

Without this test, every useful service looks like a candidate for Cove's stack. The stack grows, the operator's maintenance burden grows, and the implicit promise ("develop here, graduate to IaaS") breaks for services that don't have a commodity contract. The test forces an honest accounting: is Cove providing an affordance, or just hosting software?

## Consequences

- **ntfy and MinIO qualify** as shared platform services. They have commodity contracts and multi-vendor markets.
- **No workflow orchestrator qualifies** (Dagu, Temporal, Windmill, Argo, Airflow, Step Functions, Logic Apps, GCP Workflows).
- **Cron+HTTP-trigger and CI-pipeline-with-schedule** are the commoditized scheduling layers. Forgejo Actions with `on: schedule` already lives at this layer.
- **Services that fail the test are not banned from Cove** — they can ship as Shape 1 images that projects opt into, with eyes open about product lock-in. The test governs whether they run as shared Cove infrastructure, not whether they're available at all.
- **Future service candidates must be evaluated against this test before being added to Cove's compose stack.**

## See also

- Trove: `scheduling-orchestration-iaas@6bab1f8` — research on workflow orchestration commoditization
- Musing: `docs/musings/windmill-script-scheduler.md` — original Dagu proposal (will need revision against this ADR)
- Parley: `docs/musings/parleys/2026-07-06-dagu-essential-use-case.md` — ongoing parley on where Dagu belongs