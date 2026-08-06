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

**2026-08-06 (revisit) — REVERSED.** The operator corrected the framing: the subagent's "empty city" objection was **an adoption objection, not a tooling objection**, and Cove's identity is to provide **industry-standard tooling** (ansible, Vault, git, forge+CI) so a single dev gets real-platform leverage without hand-assembling it. A custom "step short of OTel" (log sink + correlation IDs + pull-based per-app profilers) is bespoke glue — exactly the custom stack Cove exists to avoid. **Observability belongs in the standard-tooling family; Cove should provide the actual standard (Prometheus + Grafana, OTLP when traces matter), not a smaller substitute.** The "cheaper than OTel" line of thinking is contrary to Cove's purpose and is dropped. The surviving live tension is a **timing/sequencing question** (see T5).

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

### T5: Traces — when do correlation/log-only logs stop being enough?

**Raised:** 2026-08-06
**Status:** resolved

**Resolution:** Correlation IDs in logs reconstruct *what happened in what order* but not *where latency went* — no per-span timing, no parent/child attribution. Traces are a genuine need when debugging a **cross-service latency problem** (nginx → app → vault). But on a single localhost box the hops are microseconds apart; a slow path is almost always slow *inside one service*, which is profiling territory, not tracing. So distributed tracing is the **narrowest** need — the rarest on a single-operator localhost platform — and the standard answer when it does arise is OTel, not a custom approximation.

---

### T6: Profiling — the underweighted, and cheapest, need

**Raised:** 2026-08-06
**Status:** resolved

**Resolution:** Profiling (CPU flame graphs, heap/memory) is what you reach for when an app is slow or leaking, and **no log sink, correlation ID, or Prometheus counter answers that**. But it is **per-process and pull-based** — pprof (Go), async-profiler/JFR (JVM), py-spy (Python) — needing no shared platform at all: each app exposes a profile endpoint you curl when needed. Profiling is therefore the *cheapest* observability need (less surface than even a log sink), and it is a **per-app concern, not a platform one** — it does not justify a Cove observability backend by itself. It complements, not competes with, the platform's metrics/traces role.

---

## Synthesis

**Status:** resolved — **scope decision made: build the standard stack now.**

T1's NO was reversed (tooling objection reframed as adoption/timing, contrary to Cove's identity of providing industry-standard tooling). The operator closed the remaining adoption/timing tension: **ship Prometheus + Grafana with OTLP ingestion now**, as a first-class Cove service alongside forge/vault/registry/pages. The custom "step short of OTel" idea is dropped as contrary to Cove's purpose.

**Adopted shape (from T2/T3/T4):**
- **Stack:** OTLP-first — Prometheus store/query + Grafana dashboards (T2).
- **Endpoint/auth:** `otel.cove` through nginx ingress, mTLS from local CA (T3).
- **Integration:** `cove observability init` CLI helper + auto-instrumentation (T4).

**Boundaries (from T5/T6):**
- Distributed tracing (OTLP) is the narrowest, rarest need — added when a real cross-service latency hunt requires it.
- Profiling (pprof/JFR/py-spy) is per-process and pull-based — a per-app concern, **not** a platform service. The platform's role is metrics/traces; profiling stays app-side.

**Downstream docs decision:** PURPOSE.md's identity already frames Cove as infrastructure providing services dev tools connect to (line 70), which observability fits — no mission rewrite needed. Only the service enumerations in PURPOSE.md and README's Services table get updated to add observability. This is the output of closing the scope tension.
