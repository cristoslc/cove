# Observability: Prometheus and/or OpenTelemetry?

> **Status:** Musing — half-formed, not a plan. Binary question reframed below.

## The question, reframed

"Should we add Prometheus and/or OpenTelemetry to Cove?" is a binary yes/no that closes the idea down. The open question is: **what observability does a local-first, single-operator platform actually need, and what's the cheapest way to get it?**

## Current state of Cove observability

Cove is 8 containers (forgejo, nginx, dnsmasq, dnsproxy, vault, litellm-db, litellm, headroom) behind an nginx ingress on `127.0.0.1:8443`. Observability today is:

- **`cove status`** — a CLI health check (`cli/cove/status.py`) that shells out to `docker ps` and probes each service. It's pull-based, on-demand, operator-invoked. No history, no trend, no alerting.
- **3 docker healthchecks** in `compose/docker-compose.yml` — container-level liveness only.
- **Logs** — `docker logs` / `cove litellm logs`, ad hoc.
- A prior musing, `cove-health-daemon.md`, already floats a background health daemon.

There is **no metrics collection, no time-series store, no tracing, no dashboards, no alerting.**

## The tension: local-first vs. observability stack weight

Cove's whole identity is offline-first, localhost-only, single trusted operator. Prometheus + Grafana + OTel collector is a *distributed-systems* observability stack. It brings:

- **Cost:** 2-3 more containers, memory footprint, config surface, version pinning, CVE surface (same supply-chain concern as the LiteLLM hardening musing).
- **Value:** dashboards nobody stares at, alerts that page nobody, trends for a single-user box.

For a single operator, the marginal value of a full Prometheus/Grafana deployment is low. The failure modes that matter are: "is a service up?" (already answered by `cove status`) and "is it healthy over time?" (not answered).

## What's actually worth it

The gap is **history and trend**, not collection. Options, cheapest first:

1. **Extend `cove status` to persist snapshots** — a small append-only JSON/SQLite log of check results with timestamps. Gives trend + "when did it last break" for near-zero cost. Fits the existing CLI, no new containers.
2. **Prometheus as a scrape target only** — expose a `/metrics` endpoint on the nginx ingress (and maybe vault/forgejo, which already emit Prometheus metrics natively) and scrape with a tiny Prometheus, but skip Grafana. Query via `promtool`/CLI. Middle ground.
3. **OpenTelemetry for tracing** — only worth it if we're chasing latency across the proxy chain (nginx → litellm → headroom → upstream). That's a real cross-service path, but single-operator latency debugging is rare. Lowest priority.
4. **Full Prometheus + Grafana + OTel** — the "real" stack. Overkill for now; revisit only if Cove grows multi-tenant or multi-node.

## Native metric sources worth noting

- **Forgejo** and **Vault** both expose Prometheus `/metrics` natively — so a scrape-only Prometheus would get real signal with zero instrumentation.
- **nginx** needs `stub_status` or the nginx-prometheus-exporter.
- **litellm/headroom** — unknown; would need checking.

## Lean

- Don't add a metrics stack to satisfy a generic "every platform should have observability" instinct. Add it when a concrete question can't be answered by `cove status` + logs.
- The health daemon musing and this one overlap: a persisted status history is the natural first step for both.

## Open questions

- Does the health daemon musing already propose persistence? If so, this musing is a subset.
- Is there a concrete "I couldn't tell when X broke" pain, or is this speculative?
- Would a single scrape-only Prometheus (no Grafana) be worth 1 container for native forgejo/vault metrics?
