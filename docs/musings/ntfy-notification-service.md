# ntfy as a standalone Cove notification service

Cove needs a **notification service that Cove's own services can use** — e.g. speedtest alerts when the operator's internet speed drops. This musing proposes adding **ntfy** (`binwiederhier/ntfy`) to the Cove stack as a **standalone platform service, decoupled from Dagu and MinIO**.

ntfy was previously introduced as a co-passenger in the Dagu musing (`windmill-script-scheduler.md`), landing in the same release because "Dagu needs ntfy for notifications." That framing is stale: notification delivery is a co-equal platform capability that stands on its own, and it has a concrete near-term driver — the Speedtest Tracker alert — that does **not** need Dagu at all.

## The concrete driver: speedtest → ntfy

Speedtest Tracker (`internet-link-monitoring-speedtest-tracker.md`) has webhook/apprise-style notifications. The natural alert path:

- Speedtest Tracker detects a speed drop / packet-loss blip / outage on the operator's WAN link
- Fires a webhook to `notify.cove` (ntfy)
- ntfy delivers to the operator's phone/desktop as a push notification

This is a **direct HTTP push** — Speedtest Tracker hits ntfy's publish endpoint, no Dagu involved. It's the primary concern this musing exists for: **Cove's own services consume notification delivery**, and speedtest is the first consumer.

## Why standalone (not Dagu-coupled)

The Dagu musing treated ntfy (and MinIO) as services that "land together." Three reasons to decouple:

1. **Independent driver.** Speedtest→ntfy doesn't need Dagu. Scheduling isn't a prerequisite for notification.
2. **Independent graduation path.** ntfy clears Tier 1 (core) under ADR-016 — a commoditized HTTP-push contract with a multi-vendor market (SES email, FCM/APNs mobile push, Pushover). Dagu fails that test (no commodity contract). Coupling a core candidate to a non-graduating service muddies both.
3. **Independent adoption.** If Dagu stalls, notification delivery shouldn't. The operator can stand up ntfy now for speedtest alerts and let Dagu land later on its own schedule.

## Contract and graduation (ADR-015/016)

ntfy's contract is **"HTTP push"**: `curl` a POST to a topic, subscribers receive it over websocket/SSE. That's a commodity interface — the same "change the endpoint, done" graduation story as MinIO→S3:

| Service | Contract | Graduation target |
|---|---|---|
| MinIO | S3 API | AWS S3 / R2 / Wasabi / B2 |
| ntfy | HTTP push | SES email / FCM / APNs / Pushover |

So ntfy is the notification analogue of MinIO for storage. It's Tier 1 (core) under ADR-016.

## Deployment: a container, consistent with the stack

ntfy runs as a container (`binwiederhier/ntfy`) in the compose stack, matching every other service:

- nginx ingress at **`notify.cove`** (consistent with the sole-ingress invariant, ADR-014)
- Data on a host volume (`~/Documents/cove-data/ntfy/`), caught by machine backups
- Under `cove up` + the health daemon, same as MinIO/Dagu
- Bootstrap config in `compose/.env` (existing pattern), not hand-edited

This is consistent with Cove's IaC bias — the service is declared in code, not configured by hand in a running container.

## Delivery model: local + a mobile-push relay

ntfy's delivery splits into two tiers, and the tradeoff should be explicit:

**Fully local (offline-first, no external dependency):**
- Desktop/web push — subscriber connects to `notify.cove` over websocket/SSE. Works with no internet.
- Any push received while a client is actively connected.

**Mobile push when the app is backgrounded/killed (needs an upstream):**
- When the phone isn't actively connected, your server can't reach APNs/FCM directly. ntfy is designed to relay through the **public ntfy gateway** (`ntfy.sh`): your server publishes a copy to `ntfy.sh`, which routes through Apple/Google push services to the phone.
- This is the pragmatic default for most self-hosters. The tradeoff: you depend on `ntfy.sh` being reachable, and mobile push doesn't work fully offline.

**Self-relay alternative (full offline):** run your own push bridge/proxy on a public-facing VPS, or use ntfy's upstream push connection for your own app. This cuts against Cove's offline-first identity and adds a persistent public endpoint to operate. Not worth it for a solo operator.

**Framing for the musing:** Cove's *local* notification delivery is fully self-hosted and offline-first. Only "notify you while you're away" touches an upstream — and for the speedtest use case, that's exactly what you want (the alert has to reach your phone, not just your desk). This is a conscious tradeoff, not a surprise.

## SES-from-apps: the next question, same graduation story

Once Cove delivers notifications, user apps on `*.app.cove` will ask for transactional email (the "SES from apps" question). The options:

- **Self-hosted email server (Postal etc.)** — true to offline, but running a mail server is real operational overhead and deliverability is hard. Cuts against Cove's refuse-operational-overhead identity. Also no SES-compatible self-hosted server is production-grade.
- **SMTP-send contract + endpoint swap (ntfy-style, recommended)** — keep an SMTP/HTTP-send contract in code, default to a local capture (Mailpit) for dev, and **swap the endpoint to real SES/Postmark/Mailgun/Resend in prod**. Same pattern as ntfy→SES and MinIO→S3: a commodity sending contract with a multi-vendor market.

So the answer to "SES from apps" is: **don't run an SES-compatible server.** Ship the contract, default local, graduate to a real vendor by endpoint swap. This is a future consideration for `*.apps.cove`, not something to build now — noted here so the ntfy contract is designed to accommodate it.

## What Cove ships vs. what the user writes

| Cove ships | User writes |
|---|---|
| The ntfy service at `notify.cove` (running, containerized) | Topics, subscriptions |
| nginx ingress + host volume | Webhook/publish calls from services and apps |
| Bootstrap config in `compose/.env` | Auth tokens (per-topic) when apps arrive |

Cove ships the empty service. The speedtest→ntfy wiring is a configuration of Speedtest Tracker, not a Cove-built feature.

## ADR treatment

ADR-016 names ntfy a **Tier 1 core candidate** (HTTP-push contract, multi-vendor market, endpoint-swap graduation) but does not decide how ntfy is deployed — it only establishes the rubric. This musing's decisions (standalone service decoupled from Dagu/MinIO, containerized at `notify.cove`, mobile-push relay via `ntfy.sh`, and the "contract + endpoint-swap, don't run an SES-compatible server" answer for app email) are service-specific and do not belong in the rubric.

**Recommendation: a new ADR (next number) locking in the standalone notification service**, not an amendment to ADR-016. The tiering already lives in ADR-016; the deployment decisions belong in a dedicated ADR that can be referenced by the eventual `*.app.cove` sashay. Amend ADR-016 only if the two-tier model itself changes.

## Open questions

1. **Auth for MVP?** Authless for the speedtest bootstrap. Per-topic tokens before `*.app.cove` apps use ntfy — not building this now.
2. **Mobile push upstream:** use the public `ntfy.sh` relay (default), or defer mobile push entirely until the operator wants it? Desktop push alone is fully local.
3. **Exact FQDN default** — `notify.cove` is the proposal.

## Lean

- **Boundary:** notification delivery is ntfy's only job. Don't let it creep into Cove-service uptime (OpenObserve owns that) or scheduled jobs (Dagu owns that).
- **Don't add an SES-compatible server.** The contract-and-swap pattern covers app email without operating a mail server.

## Related artifacts

- `docs/adr/adr-015-iaas-graduation-test.md` — the graduation test ntfy passes
- `docs/adr/adr-016-two-tier-service-adoption-rubric.md` — ntfy clears Tier 1
- `docs/musings/internet-link-monitoring-speedtest-tracker.md` — the speedtest driver; open question #2 wires to ntfy
- `docs/musings/windmill-script-scheduler.md` — where ntfy previously landed as a Dagu passenger
