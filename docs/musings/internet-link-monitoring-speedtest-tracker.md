# Internet link monitoring: Speedtest Tracker (operator-facing)

> **Status:** Musing — exploratory. Research narrowed the tool choice to **Speedtest Tracker**; see open questions before this becomes a build decision.

## The idea

Add **Speedtest Tracker** (`alexjustesen/speedtest-tracker`) to the Cove stack with a **narrow scope: monitor the operator's internet connection** — uptime, latency, and bandwidth of the machine's WAN link.

This is deliberately *not* about monitoring Cove's own services. Cove service availability is handled by **OpenObserve** (via a blackbox prober → OTLP), per the observability musing — the operator is happy with OpenObserve for that slice.

## Why Speedtest Tracker, not Uptime Kuma

Initial framing proposed **Uptime Kuma**. Research (and the operator's narrowing to "mostly interested in internet connectivity") flipped the choice:

- **Kuma's bandwidth gap.** Kuma cleanly does uptime + latency, but its `speedtest` feature tests Kuma's *own* server against public speed servers — it does **not** measure the local client's WAN link. So Kuma would still need a companion speedtest runner for the bandwidth slice.
- **Speedtest Tracker covers all three in one container.** It schedules Ookla `speedtest` CLI runs and graphs **download, upload, latency/ping, jitter, packet loss** over time. That's the operator's entire internet wishlist (uptime + latency + bandwidth) with no companion service. Single container, no external deps, SQLite-backed.
- **Uptime Kuma's niche** (point-and-click status page + incident timeline) is valuable only if the operator wants a status-page UI — not the goal here. OpenObserve already owns Cove-service uptime, so Kuma would be redundant for the app-facing slice and weak for the bandwidth slice.

**Alternatives considered:** Smokeping (latency-only, rough edges); Gatus (YAML-as-code, no bandwidth, overkill for solo ISP watch); OpenObserve + `speedtest-exporter` (reuses the platform but is more assembly than Speedtest Tracker). Speedtest Tracker is the cleanest fit.

## Scope split (the important boundary)

| Axis | Owned by | Mechanism |
| --- | --- | --- |
| Cove services' uptime | **OpenObserve** | blackbox probe → OTLP (fits the existing observability platform) |
| Operator internet link | **Speedtest Tracker** | scheduled Ookla speedtest (down/up/latency/jitter/packet loss) |

So Speedtest Tracker here is a **single-purpose, operator-facing** service for the WAN link — not a general Cove-monitoring or app-monitoring platform. Cheap (one container, zero deps), avoids overlap with OpenObserve.

## Why a prober at all

The observability musing's OpenObserve is a **passive store** — it ingests OTLP but doesn't *probe*. The WAN link needs active measurement, and Speedtest Tracker is the purpose-built, zero-assembly option for that.

## What needs monitoring

- **Uptime / packet loss** — Speedtest Tracker records packet loss per test, surfacing ISP blips vs. local outages. Critical for debugging "is it my machine or my connection."
- **Latency** — ping RTT + jitter history. Detects jitter/saturation, wireless degradation.
- **Bandwidth** — download/upload over time via Ookla speedtest CLI.

## Design sketch

- **Speedtest Tracker as a Cove service** in the compose stack behind the nginx ingress (e.g. `status.cove`), consistent with the sole-ingress invariant (ADR-014). Needs a small SQLite/volume for its database, like litellm-db.
- **Auth:** Speedtest Tracker has its own login; via nginx ingress it should sit behind at least basic auth or the platform's usual bearer/gate, matching how other `*.cove` app-facing services are exposed.
- **Scheduling:** a default test interval so `cove up` gives instant value. Speedtest Tracker runs on a cron/schedule internally.
- **Operator-facing only** — no public status page; no one else cares about the operator's WAN.

## Open questions

- Does Speedtest Tracker's own login suffice behind the nginx ingress, or does it need the platform's auth gate layered on top (consistency with other `*.cove` services)?
- Notification path: Speedtest Tracker has webhook/apprise-style notifications — wire to ntfy, or is the dashboard enough?
- Exact FQDN and test interval defaults.

## Lean

- Keep the boundary: **OpenObserve = Cove services' uptime; Speedtest Tracker = internet link.** Don't let it creep into Cove-service monitoring (that would duplicate the observability platform).
- Don't re-add Uptime Kuma or a Prometheus/Grafana stack — Speedtest Tracker's dashboard is the whole point.
