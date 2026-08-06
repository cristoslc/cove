---
title: "Parley: Cove Observability Platform"
date: 2026-08-06
topic: observability-prometheus-otel
status: in_progress
---

# Parley: Cove Observability Platform

## Opening Position

The musing reframes observability for Cove as a **platform capability** — an instrumentation/observability backend that apps running on Cove can use — with Cove's own services as a secondary consumer. The proposed shape is **OTel as the ingestion lingua franca → Prometheus as store/query → Grafana for dashboards**, consumed via a single documented ingestion endpoint. This is the same platform-vs-tool shape as "does Cove provide a vault, or does each app roll its own secrets?"

Cove context: local-first, offline, single trusted operator, ~8 containers behind nginx ingress on `127.0.0.1:8443`, `*.cove` DNS via `/etc/resolver`, apps run on the platform.

## Tension Backlog

Each open question from the musing is dispatched to a subagent for an adversarial answer (position + reasoning). Resolutions appended below.

## Tensions

### T1: Scope — is an observability backend core platform surface or scope creep?

**Raised:** 2026-08-06 (subagent)
**Status:** open — this is the dominant tension and it cuts against the premise

**Resolution (subagent position, firm NO):** The platform-vs-tool analogy cuts *against* shipping a full OTel/Prometheus/Grafana backend. Vault and the registry earn their place because apps themselves consume them; an observability backend is only useful if apps emit telemetry, and most don't — Cove is not a dev environment, so instrumenting apps is the developer's job. Shipping a backend no app emits into is "a cathedral in an empty city." It also adds four services, four config surfaces, and an entire vocabulary (scrape configs, service discovery, retention) that a "one command, zero configuration" platform must own forever. **Recommendation: ship only a log sink (one container, one FQDN, no agent on apps) plus an nginx access-log endpoint. Add full observability only the day Cove needs it to debug itself.**

**Flip condition:** when Cove's own services (or an app the operator genuinely cares about) hit a debugging wall that logs can't answer.

**Cross-tension:** T2/T3/T4 all assume the backend exists. If T1's NO holds, T2-T4 are moot. The scope decision must be settled before stack shape.

---

### T2: Stack shape — OTLP-first vs scrape-endpoint-per-app

**Raised:** 2026-08-06 (subagent)
**Status:** resolved (conditionally, assuming backend exists)

**Resolution:** **OTLP-first.** The OTel collector is not an extra container "for its own sake" — it is the single trust boundary that terminates transport, validates, and normalizes all telemetry before it hits a store. One wire protocol covers metrics+traces+logs; one TLS/config surface; one fan-out point. The app contract shrinks to "emit OTLP," richer and stabler than "each app self-hosts a Prometheus exporter." The scrape model's "no container" is a myth of savings: every exporter is its own config surface, its own CVEs, its own /metrics endpoint poking through nginx — N attack surfaces vs the collector's one.

**Counterargument:** Prometheus scrape is the KISS default and covers ~90% of what a single operator needs (metrics); OTLP traces/logs are underexploited when one person reads dashboards.

**Flip condition:** if Cove apps never ship traces/logs and metrics-only suffices, the collector is dead weight — go scrape-per-app + shared Grafana, revisit OTLP when a real multi-service trace need emerges.

---

### T3: Consumption path — endpoint location and auth

**Raised:** 2026-08-06 (subagent)
**Status:** resolved (conditionally)

**Resolution:** **`otel.cove` through the nginx ingress, authenticated by mTLS from the local CA.** nginx is the *sole* ingress (ADR-014) — no service publishes a host port, and a compose-internal network breaks that invariant while forcing every app to join a private network. mTLS from the local CA reuses the same trust root already in the system store, so an app gets a client cert with no secret to leak, no Vault round-trip at startup, no chicken-and-egg (an app must reach Vault *before* emitting telemetry, which is backwards). A Vault bearer token adds a secret + bootstrap dependency; trusting loopback is too weak (one compromised app can spoof another's telemetry).

**Counterargument:** mTLS is the heaviest integration — OTel SDKs don't do client certs natively, so every app needs a custom exporter; and the threat model (malicious app on your own single-operator box) is already game-over, making it ceremony for a nonexistent threat.

**Flip condition:** if collector mTLS proves operationally painful (SDK friction, cert rotation) or we declare apps trusted tenants, drop to a Vault-issued per-app bearer token.

---

### T4: App-facing integration — compose snippet vs template repo vs CLI helper

**Raised:** 2026-08-06 (subagent)
**Status:** resolved (assuming backend exists)

**Resolution:** **A CLI helper — `cove observability init`** — that edits the app's compose file and .env, rather than a bare documented snippet or a template repo. The operator is one person running a handful of apps; friction is adoption, and documentation is the highest-friction surface (read, copy, version drift). A CLI helper turns a three-step README chore into one idempotent command: detect the target compose service, inject `OTEL_EXPORTER_OTLP_ENDPOINT` + service-name env var, append the collector/agent container. **Auto-instrumentation (zero-code OTLP) wins over manual SDK wiring** for arbitrary apps the operator doesn't own internally.

**Counterargument:** a CLI that rewrites compose files is more code to maintain and competes with template-repo pre-wiring, which is genuinely zero-friction for greenfield apps.

**Flip condition:** if most Cove apps become template-sourced greenfield scaffolds, drop the CLI and let the scaffold own telemetry.

---

## Synthesis

T1 is the load-bearing tension and it is **unresolved** — a firm NO that challenges the premise of the musing. T2/T3/T4 are the shape, but only matter if T1 resolves to "build it." The parley's actionable output: before any stack work, decide scope. The default position from this parley is **do not build the full backend now**; the cheapest testable increment that preserves optionality is the **log sink + nginx access-log endpoint** from T1. If that proves insufficient for debugging Cove itself or a real app, escalate to OTLP-first (T2), mTLS `otel.cove` (T3), `cove observability init` (T4).
