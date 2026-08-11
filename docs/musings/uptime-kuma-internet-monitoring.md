# Uptime Kuma: availability monitoring + operator internet monitoring

> **Status:** Musing — exploratory, not yet resolved.

## The idea

Add **Uptime Kuma** (`louislam/uptime-kuma`) to the Cove stack as a monitoring service with three purposes:

1. **Monitor Cove's own services** — black-box availability checks (HTTP, ping, port) against Forgejo, Vault, nginx, MinIO, ntfy, litellm, etc. This is what a pull-based `cove status` cannot do: history, trends, incident timeline, notifications.
2. **Be a monitoring platform for operator app dev** — the same "platform capability, not tool" argument as vault/registry/observability. An app the operator deploys on Cove gets a place to register uptime/status-page checks without self-hosting Kuma.
3. **Monitor the operator's internet connection** — uptime, latency, and bandwidth of the machine's WAN link. This is the part that goes beyond Cove's own services.

## How it relates to the observability musing

`docs/musings/observability-prometheus-otel.md` settled on **OpenObserve** as a single OTLP container (metrics + logs + traces + APM dashboards) for apps. That is *internal* instrumentation — emitted by apps, about their own health and performance.

Uptime Kuma is a different axis: **black-box external availability**. It observes from the outside ("is this endpoint up?"), not via agent instrumentation. The two are complementary, not competing:
- OpenObserve = "why is my service slow/broken" (depth)
- Uptime Kuma = "is my service actually reachable, and has it been flapping" (breadth)

This distinction matters so we don't cargo-cult one onto the other. Kuma is cheap and purpose-built; OpenObserve does not make Kuma redundant and vice-versa.

## Internet monitoring is the genuinely new part

Monitoring Cove's own services is nearly a subset of the observability musing's self-observation slice (and the health daemon, `docs/musings/cove-health-daemon.md`). The **operator internet link** piece is what's absent from every existing musing:

- **Uptime** — packet-loss / reachability of a few public hosts (e.g. `1.1.1.1`, `8.8.8.8`) to detect ISP blips vs. local outages. Critical for debugging "is it my machine or my connection."
- **Latency** — ICMP/ping RTT history. Detects jitter/saturation, wireless degredation.
- **Bandwidth** — this is the hard part. Kuma does not do active speed tests natively. Options:
  - Kuma `speedtest` monitor type — there is no first-class speedtest in upstream Kuma for the WAN link (its speedtest feature is for testing Kuma's own server upload/download against public speed servers, not the *operator's* client link from a local Kuma instance). May need a custom approach.
  - A scheduled **Speedtest-cli/Ookla `speedtest`** container (e.g. `mback2k/speedtest-exporter` / `speedtest-tracker`) that runs periodically and stores history — separate from Kuma, could feed a dashboard.
  - Or a lightweight periodic script that pings a CDN and measures a download probe.

So "bandwidth" likely needs a companion piece, not Kuma alone. Kuma cleanly handles uptime + latency; bandwidth needs a speedtest-runner (speedtest-tracker or an exporter) possibly plus Grafana/OpenObserve for the trend graph.

## Design sketch

- **Kuma as a Cove service** in the compose stack behind the nginx ingress (e.g. `status.cove`), consistent with the sole-ingress invariant. Needs a small SQLite/volume for its database, like litellm-db.
- **Auth:** Kuma has its own login; via nginx ingress it should sit behind at least basic auth or the platform's usual bearer/gate, matching how other `*.cove` app-facing services are exposed.
- **Default monitors for Cove services** shipped in a seed file (like `compose/seeds/` for Vault) — a curated set of HTTP checks for the core services, so `cove up` gives instant value.
- **Internet monitors:** a public-host ping group. Bandwidth is an open sub-question (below).

## Open questions

- Does internet-link monitoring belong in Kuma, or in a dedicated **speedtest-tracker** service, or split (Kuma = up/latency, speedtest-tracker = bandwidth)?
- Is there a first-class Kuma `speedtest` monitor for the *local* client's WAN, or is that feature only for testing Kuma's own server? (I believe the latter.)
- Does this fold into the health daemon/observability work, or stand alone as a lighter separate service? Kuma is one container with zero external deps — cheap enough to stand alone.
- Is a public status page for the internet link desirable, or is this purely operator-facing (local `status.cove`)?

## Lean

- Don't duplicate the observability musing — keep the line: OpenObserve = internal instrumentation, Kuma = external availability. Don't let Kuma grow Prometheus/Grafana ambitions.
- Bandwidth is the novel, hard slice; uptime/latency on public hosts is nearly free in Kuma. Solve the easy parts first, treat bandwidth as its own mini-decision.
