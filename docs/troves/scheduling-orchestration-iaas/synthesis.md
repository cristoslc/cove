# Synthesis: Scheduling & Orchestration as Commoditized IaaS

## Question this trove answers

Does workflow scheduling / orchestration have a commoditized IaaS layer — a vendor-neutral contract with a multi-vendor market — the way notification (ntfy→SES/FCM/Pushover) and object storage (MinIO→S3/R2/Wasabi/...) do? If so, what is the contract? If not, what *is* portable?

## Key findings

### 1. No commoditized workflow-orchestration contract exists at the workflow-DSL layer

Every major orchestrator speaks its own format. There is no S3-equivalent — no de-facto standard DSL that multiple IaaS vendors accept.

| Engine | Format | Vendors that speak it |
|---|---|---|
| Dagu | Dagu YAML | 1 (Dagu / Managed Dagu) |
| Windmill | Windmill apps | 1 (Windmill Cloud) |
| Temporal | Temporal Workflows-as-Code | 1 (Temporal Cloud) |
| Airflow | Airflow DAGs (Python) | 1 (Astronomer, Google Cloud Composer — but same engine, same DAGs) |
| Argo Workflows | Argo YAML | 1 (Akuity, Codefresh — same engine) |
| AWS Step Functions | Amazon States Language (ASL) | 1 (AWS only) |
| Azure Logic Apps | Logic App JSON | 1 (Azure only) |
| GCP Workflows | Google Workflows YAML | 1 (GCP only) |

The "managed cloud" of each is just the same vendor hosting their own format. **Unlike S3 or HTTP push, there is no multi-vendor contract at the workflow-definition layer.** ([xgrid-temporal-airflow-argo], [akka-temporal-alternatives], [bytebase-oss-orchestration])

### 2. The only real standardization attempts are specs, not markets

Two vendor-neutral DSL specifications exist, both with reference runtimes, both CNCF/OASIS-backed:

- **Serverless Workflow DSL** (CNCF Sandbox, 1.0.0 released, v1.0.3 current). Declarative YAML, vendor-neutral. Reference runtime: **Synapse** (.NET). Other runtimes: **Apache KIE SonataFlow**, **Lemline**. ([cncf-serverless-workflow-project], [serverless-workflow-spec-readme], [serverless-workflow-io], [deepwiki-serverless-workflow])
- **TOSCA** (OASIS standard, v1.0 2014, v2.0 committee spec 2025). Topology + orchestration. YAML profile. Runtimes: **Cloudify**, **xOpera**, **Alien4Cloud**, **MiCADO**. ([oasis-tosca-spec], [oasis-tosca-tc], [wikipedia-tosca])

**Critical caveat — both are specifications, not markets.** The Automatiko blog puts it directly: "Being a standard (or specification) goes after a need to be portable, in many cases it ends up the same way that extensions are required." Each implementation adds extensions to be useful, breaking the portability promise. Synapse is a reference implementation, not a production-grade ecosystem with multiple IaaS vendors accepting the same DSL. **No hyperscaler accepts Serverless Workflow DSL or TOSCA natively.** ([automatiko-serverless-vs-bpmn])

So at the *workflow-definition* layer, commoditization has been attempted (specs exist) but has **not produced a multi-vendor market**. The specs are vendor-neutral in principle; in practice each runtime extends them and no hyperscaler speaks them.

### 3. The commodity is at the layer BELOW the orchestrator — cron + your code + your container

The genuinely commoditized interface for scheduled work is **cron syntax + an HTTP/container trigger**, not a workflow DAG. Every hyperscaler offers it:

| Service | Trigger contract | Compute target | Portability |
|---|---|---|---|
| AWS EventBridge Scheduler | cron + HTTP/Lambda/SQS/270+ targets | Your code | **vendor-locked to AWS targets** |
| GCP Cloud Scheduler | cron + HTTP/PubSub/AppEngine | Your code | **vendor-locked to GCP targets** |
| Azure Functions Timer | cron + Functions | Your code | **vendor-locked to Azure Functions** |
| Kubernetes CronJob | cron + container spec | Your container | **portable across any K8s** |
| GitHub Actions `on: schedule` | cron + Actions runner | Your checked-out repo | **portable across CI vendors that speak Actions-compatible YAML** |
| Forgejo Actions `on: schedule` | (same) | (same) | (same) |
| GitLab scheduled pipelines | cron + .gitlab-ci.yml | Your runner | **portable across CI vendors that speak GitLab YAML** |

The only one of these that's *cross-vendor portable* is **Kubernetes CronJob** — because Kubernetes itself is the commodity, and every certified K8s cluster speaks the same CronJob spec. The hyperscaler cron services all accept cron syntax but each only triggers their own compute. ([uplift-cloud-scheduling-services], [k8s-cronjob-docs], [sma-replace-k8s-cronjob])

### 4. The CI pipeline is the de-facto "workflow orchestration" commodity for code-bound work

For "scheduled jobs that run with the project's own tooling" — the essential use case that started this parley — the dominant commoditized shape isn't a workflow engine at all. It's a **CI pipeline with a cron trigger**:

- Same repo + same tooling + same checkout → portability is at the *pipeline format* layer, not a workflow DSL
- GitHub Actions / Forgejo Actions / GitLab CI all support `on: schedule` and share conceptual DNA
- The "swap to IaaS in prod" affordance is *weak* (each CI vendor has its own YAML) but *better than workflow engines* (CI YAML is closer to a commodity than Temporal/Dagu/Airflow DAGs)

This is the layer Forgejo Actions already lives at. The orchestrator market at this layer is fragmented but the conceptual model is portable.

### 5. There is no "develop on cove, swap to IaaS for prod" affordance for workflow orchestration

This is the sharp finding. Comparing to ntfy and MinIO:

| Service | Local contract | Prod swap | Multi-vendor market? |
|---|---|---|---|
| ntfy | HTTP POST to topic | Change endpoint URL → SES/FCM/Pushover | Yes (push/SMS/email) |
| MinIO | S3 API | Change endpoint URL → S3/R2/Wasabi/B2 | Yes (dozens) |
| Dagu | Dagu YAML DAGs | Rewrite to Managed Dagu (same vendor) or rewrite to a different orchestrator entirely | No |
| Temporal | Temporal Workflows | Change endpoint → Temporal Cloud (same vendor, same format) | No |
| Argo Workflows | Argo YAML | Same engine on managed K8s (Akuity/Codefresh) | No |
| Serverless Workflow DSL | Synapse runtime | Rewrite to SonataFlow or another runtime, *if* no extensions were used | Theoretically yes, practically no |

The "swap endpoint" pattern only works when the *contract* is commodity. Workflow orchestration has no commodity contract at the orchestration layer, so the affordance does not exist for it. The closest thing is cron+HTTP at the trigger layer (Layer 3 above), and even there the compute target is vendor-locked.

## Points of agreement across sources

- The workflow-orchestration space is fragmented by design; each tool targets a different "architectural flavor" (data pipelines vs microservices vs K8s-native vs business processes). There is no "one tool to rule them all." ([xgrid-temporal-airflow-argo])
- Standards bodies have tried (CNCF Serverless Workflow, OASIS TOSCA) and produced specifications, but adoption by hyperscalers as a *native* format is zero. ([automatiko-serverless-vs-bpmn], [oasis-tosca-tc])
- Kubernetes CronJob is the only cross-vendor-portable scheduling primitive, because K8s is the commodity. ([k8s-cronjob-docs], [sma-replace-k8s-cronjob])

## Points of disagreement

- Whether specification projects (Serverless Workflow, TOSCA) are *succeeding* at portability. CNCF/marketing says yes; practitioners (Automatiko blog) note extensions break the promise. The truth is: they're vendor-neutral in theory, single-runtime in practice.
- Whether "workflow-as-code" (Temporal) or "workflow-as-config" (Dagu, Argo, Serverless Workflow DSL) is the right authoring model. No consensus; each is optimized for a different audience.

## Gaps

- No source directly addressed "does a multi-vendor IaaS market exist for workflow orchestration?" — this trove synthesizes that finding from the absence of evidence + the fragmentation visible across sources.
- No source compared ntfy/MinIO-style commodity interfaces to workflow orchestrators directly. That comparison is the trove's contribution.
- Production adoption numbers for Synapse / SonataFlow / Serverless Workflow DSL are not published in any source found. Likely very low.
- No source addressed the *essential use case* framing (per-project scheduling with project tooling) specifically. The trove connects that framing to the findings.

## Conclusion

**Workflow scheduling / orchestration is NOT commoditized at the IaaS layer.** Unlike notification (HTTP push, commodity contract) or object storage (S3 API, commodity contract), every workflow orchestrator speaks a product-specific format with no multi-vendor market. Standardization attempts (CNCF Serverless Workflow, OASIS TOSCA) exist as specifications but have not produced a hyperscaler-accepted commodity contract.

The only commoditized scheduling primitive is **cron syntax at the trigger layer**, and the only cross-vendor-portable compute target for cron is **Kubernetes CronJob** (because K8s is the commodity). For code-bound scheduled work, the closest thing to a commodity is the **CI pipeline with a scheduled trigger** (GitHub/Forgejo/GitLab Actions), where the portability is at the pipeline-format layer rather than a workflow-DSL layer.

Implication for Cove: there is no "develop on cove, swap to IaaS for prod" affordance for workflow orchestration that is equivalent to ntfy→SES or MinIO→S3. If Cove ships a workflow orchestrator (Dagu, Temporal, Windmill, Argo, anything), it's a product lock-in choice, not a commodity contract. The commoditized layer Cove *could* provide is cron+HTTP-trigger or CI-pipeline-with-schedule, both of which it already has via Forgejo Actions.

## Sources cited

- [xgrid-temporal-airflow-argo] — https://www.xgrid.co/resources/temporal-vs-airflow-vs-argo-workflow-orchestration/
- [akka-temporal-alternatives] — https://akka.io/blog/temporal-alternatives
- [bytebase-oss-orchestration] — https://www.bytebase.com/blog/top-open-source-workflow-orchestration-tools/
- [uplift-cloud-scheduling-services] — https://upliftorch.com/tools/cron-parser/en/blog/cron-cloud-services.html
- [cncf-serverless-workflow-project] — https://www.cncf.io/projects/serverless-workflow/
- [serverless-workflow-spec-readme] — https://github.com/serverlessworkflow/specification/blob/main/README.md
- [serverless-workflow-io] — https://serverlessworkflow.io/
- [automatiko-serverless-vs-bpmn] — https://blog.automatiko.io/2022/05/15/serverless-vs-bpmn.html
- [oasis-tosca-spec] — https://docs.oasis-open.org/tosca/TOSCA/v1.0/TOSCA-v1.0.html
- [oasis-tosca-tc] — https://www.oasis-open.org/committees/tc_home.php?wg_abbrev=tosca
- [wikipedia-tosca] — https://en.wikipedia.org/wiki/OASIS_TOSCA
- [k8s-cronjob-docs] — https://kubernetes.io/docs/concepts/workloads/controllers/cron-jobs/
- [sma-replace-k8s-cronjob] — https://smatechnologies.com/blog/replace-kubernetes-cronjob-scheduler
- [deepwiki-serverless-workflow] — https://deepwiki.com/serverlessworkflow/specification
- [gillesbarbier-serverless-workflow-dsl] — https://gillesbarbier.medium.com/understanding-the-serverless-workflow-1-0-dsl-6e874a1fd511