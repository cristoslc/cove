# Observability: Prometheus and/or OpenTelemetry?

> **Status:** Musing — half-formed, not a plan. Binary question reframed below.

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

## Open questions

- Does Cove's value proposition extend to providing an observability backend, or is that scope creep beyond forge/vault/registry/pages?
- Is OTLP-first + Prometheus-store + Grafana the right shape, or does a lighter "prometheus scrape endpoint per app + shared grafana" suffice?
- Where would the ingestion endpoint live and how would an app on Cove authenticate to it?
- What's the minimal app-facing integration (compose snippet? template repo? CLI helper)?
