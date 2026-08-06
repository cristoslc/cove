# Observability: Prometheus and/or OpenTelemetry?

> **Status:** Musing — **resolved into a build decision.** Binary question reframed below. A parley (record: `docs/musings/parleys/2026-08-06-observability-platform.md`) probed the premise adversarially; see the **Parley outcome** section.

## The question, reframed

"Should we add Prometheus and/or OpenTelemetry to Cove?" is a binary yes/no that closes the idea down. The open question is: **should Cove ship an instrumentation/observability platform that apps can use — and, as a secondary benefit, use it to observe its own services?**

## The primary purpose: an observability platform for apps, not self-monitoring

My first pass got this backwards, framing it as "how does Cove monitor itself?" That's a secondary benefit. The primary is: **Cove is a place where apps run. Those apps need somewhere to send metrics, traces, and logs.** Today Cove offers them nothing — an app on Cove that wants observability has to bolt on its own Prometheus/Grafana/OTel, which for a single app is heavy and duplicated.

So the real question is about **Cove's surface area as a platform**: does a local developer platform provide an observability backend as a first-class capability (the way it provides forge, vault, registry, pages)? Or is observability left to each app to self-host?

This is a **platform-vs-tool** decision, same shape as "does Cove provide a vault, or does each app roll its own secrets?"

## What a Cove observability platform would look like

As a platform capability, it needs to be **easy to consume** — not a stack you have to administer. Sketch:

- **OTel as the ingestion lingua franca.** Apps emit OTLP (metrics + traces + logs) to a single collector endpoint. One protocol, one integration path. The collector is the workhorse.
- **Prometheus as the backend/store.** The collector scrapes and/or receives, Prometheus stores time-series, PromQL for query. Prometheus is the de-facto standard query surface.
- **Grafana for visualization** — dashboards per app. Optional but the payoff.
- **An app-facing integration** — a documented endpoint (`https://otel.cove` or similar) plus a template/snippet so an app on Cove can emit telemetry in ~1 line. Maybe a compose snippet for the OTel agent.

This reframes the cost math: 2-3 containers for the platform (collector, prometheus, grafana) is justified **not** by Cove's own self-monitoring but by being a shared capability **all** apps can use. That's the same argument that justifies vault/registry as platform services.

## Secondary benefit: Cove observes itself

Once the platform exists, Cove's own services become consumers, closing the observability gap (`cove status` is pull-based, no history, no trend). This is a nice follow-on, but it is **not** the justification for building the platform. If we only wanted to monitor Cove itself, a persisted status history would be cheaper.

## The tension: local-first, single-operator

Cove is offline-first, localhost-only. A metrics stack adds memory, config surface, and CVE/supply-chain surface (same concern as the LiteLLM hardening musing). But that cost is only worth debating **once we've decided the platform question** — whether observability is a Cove capability or a per-app responsibility.

## Native metric sources (for the self-observation slice)

- **Forgejo** and **Vault** expose Prometheus `/metrics` natively.
- **nginx** needs `stub_status` or an exporter.
- **litellm/headroom** — unknown; would need checking.

## Lean

- Don't scope this to "monitor Cove" — that's the tail wagging the dog. The platform-for-apps framing is what makes 2-3 containers worth it.
- If observability stays a per-app responsibility, then a full stack is overkill and the cheap `cove status` persistence path wins. The platform framing is what tips the balance.

## Parley outcome

A parley with adversarial subagents probed the premise. **The initial finding (T1) cut against the platform framing** — that the vault/registry analogy may not hold because an observability backend is only useful if apps emit telemetry. That objection was **reversed on reframe**: it was an adoption objection, not a tooling one, and Cove's identity is to provide **industry-standard tooling** so a single dev gets real-platform leverage without hand-assembling it. A custom "step short of OTel" would be exactly the bespoke glue Cove exists to avoid.

**Decision (operator): build the standard stack now.** Prometheus + Grafana with OTLP ingestion, shipped as a first-class Cove service alongside forge/vault/registry/pages — the industry standard, not a smaller substitute.

Adopted shape:
- **OTLP-first** — Prometheus store/query + Grafana dashboards (collector as single trust boundary, one protocol for metrics+traces+logs).
- **`otel.cove` through the nginx ingress, mTLS** from the local CA (sole-ingress invariant, no secret/Vault bootstrap).
- **`cove observability init` CLI helper** (idempotent compose/.env edit) with auto-instrumentation over manual SDK wiring.

Boundaries:
- **Distributed tracing** (OTLP) is the narrowest, rarest need — added as the standard when a real cross-service latency hunt requires it.
- **Profiling** (pprof/JFR/py-spy) is per-process and pull-based — a **per-app concern, not a platform service**. The platform's role is metrics/traces; profiling stays app-side.

**Docs consequence:** PURPOSE.md's identity already frames Cove as infrastructure providing services dev tools connect to (PURPOSE.md:70) — observability fits, no mission rewrite. Only the service enumerations in PURPOSE.md and README's Services table get observability added.

## Open questions

All original scope/shape questions are **settled by the parley** (record: `docs/musings/parleys/2026-08-06-observability-platform.md`):

- **Scope** (T1) → **build the standard stack now** — Prometheus + Grafana, OTLP ingestion, first-class Cove service.
- **Stack shape** (T2) → **OTLP-first** over scrape-endpoint-per-app.
- **Endpoint/auth** (T3) → **`otel.cove` via nginx ingress, mTLS from local CA**.
- **Integration** (T4) → **`cove observability init` CLI helper + auto-instrumentation**.
- **Traces** (T5) → added via OTLP when a real cross-service latency hunt requires it (narrowest need).
- **Profiling** (T6) → per-app concern (pprof/JFR/py-spy), **not** a platform service.

**Next:** this musing → `docs/plans/` plan → sashay (branch + worktree + draft PR + subagent dispatch). The plan must pin the stack, the `otel.cove` nginx + mTLS wiring, the CLI helper, and the PURPOSE.md/README service-enumeration update.
