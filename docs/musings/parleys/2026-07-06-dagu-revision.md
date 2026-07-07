---
title: "Parley: Dagu as Cove's Script Scheduler"
date: 2026-07-06
topic: windmill-script-scheduler
status: in_progress
---

# Parley: Dagu Revision

## Opening Position

The musing proposes adding Dagu to the Cove compose stack as **platform infrastructure** — a scheduling service available to the operator and to user apps, alongside Forgejo, Vault, MinIO, and ntfy. Dagu is not a Cove manager. It does not ship Cove-specific DAGs, does not restart Cove containers, does not monitor Cove health. Cove ships the empty service; the operator/user writes their own DAGs.

This framing emerged during the parley. The original musing positioned Dagu as a Cove manager (health checks, backups, cert renewal as Cove-shipped DAGs) with a Docker API proxy for safe `container:` step spawning. Both of those were rejected — Dagu is platform infra, and it runs `run:` steps inside a custom cove-tools image with no Docker socket access at all.

## Tension Backlog

All tensions raised during the parley are resolved below. No open tensions remain.

## Tensions

### T1: Output Storage Circular Dependency

**Raised:** 2026-07-06
**Status:** resolved

**Resolution:** Add MinIO as Cove infrastructure (bootstrapped by Dagu backup use case, intended for all services). MinIO writes to a host-mounted directory (`~/Documents/cove-data/minio/`), so objects are real files caught by regular machine backups (Time Machine, restic, etc.). No MinIO-specific backup needed — it's just a structured filesystem with an S3 API on top.

DAGs push outputs to MinIO via S3 API. This also resolves T2 (no proxy needed) — with a storage target, `run:` steps in a cove-tools image can do everything: curl Cove APIs for data, mc/curl MinIO for storage. No `container:` step type, no socket access, no proxy.

---

### T2: Proxy Complexity vs. Pattern B

**Raised:** 2026-07-06
**Status:** resolved

**Resolution:** Drop the Docker API proxy. Drop the `container:` step type. Build `cove-tools` (Alpine + curl + openssl + jq + python3 + mc) as the Dagu container image. All DAGs run as `run:` steps inside cove-tools. Dagu has no Docker socket access at all — no proxy, no raw socket, no lethal trifecta. The proxy was ~100 lines of Go to enable a feature (per-step containers) that Cove doesn't need. cove-tools is a Dockerfile — trivially simpler.

---

### T3: Health checks without recovery

**Raised:** 2026-07-06
**Status:** resolved (moot)

**Resolution:** This tension was based on the stale framing where Dagu manages Cove health. Dagu is platform infra, not a Cove manager. If the operator wants health monitoring via Dagu, they write their own health-check DAG that calls Cove HTTP APIs and publishes alerts to ntfy. That's a user workflow, not Cove infrastructure. The notification path (ntfy) was resolved in T8.

---

### T4: Network egress from spawned containers

**Raised:** 2026-07-06
**Status:** resolved (moot)

No spawned containers — cove-tools runs as a single container with no socket access. Network egress is whatever Docker Compose networking allows (Cove internal network only).

---

### T5: cove-tools portability claim

**Raised:** 2026-07-06
**Status:** resolved (deferred)

cove-tools claimed reusable in swain-box. swain-box is a VM with no Docker. For cove-tools to work there, either Docker gets installed in the VM or cove-tools ships as a native package. The image is portable; the *consumption* path isn't. Defer until swain-box actually needs it — not a blocker for the Dagu sashay.

---

### T6: Cert check fidelity

**Raised:** 2026-07-06
**Status:** resolved (moot)

This tension was based on the stale framing where Cove ships a cert-renewal DAG. Dagu is platform infra, not a Cove manager. If the operator wants cert monitoring via Dagu, they write their own DAG. The fidelity of `openssl s_client` vs filesystem cert checks is a user workflow concern, not a Cove architecture decision.

---

### T7: MinIO as Cove infrastructure

**Raised:** 2026-07-06
**Status:** resolved

MinIO is general Cove infra, bootstrapped by the Dagu backup use case. Same for ntfy (T8). Both are platform services that user apps at `*.app.cove` will consume in the future. Cove crossed the platform threshold — these aren't Dagu dependencies, they're Cove capabilities that Dagu tipped over the edge.

---

### T8: Notification bus as Cove infrastructure

**Raised:** 2026-07-06
**Status:** resolved

ntfy (self-hosted, single Go binary, no database, ~20MB) as general Cove notification infra at `notify.cove`. Bootstrapped by Dagu health alerts, intended for all Cove services and user apps. Same pattern as MinIO.

---

### T9: Platform scope creep

**Raised:** 2026-07-06
**Status:** resolved

Adding Dagu + MinIO + ntfy in one musing could look like scope creep. Reframe: Cove was a 5-service stack serving itself. Adding a 6th service (Dagu) that *runs jobs* tips several latent needs over threshold simultaneously. These are platform capabilities Cove was too small to justify before. Not scope creep — threshold crossing.

Roadmap horizon: `*.app.cove` — user apps consuming MinIO, ntfy, Dagu as platform APIs. Not building this now, but architecting so it fits naturally when we get there. C4 diagrams (T10) will validate the topology evolves without rearchitecture.

---

### T10: C4 diagrams to disentangle states

**Raised:** 2026-07-06
**Status:** resolved

Four C4 container diagrams: current state, Dagu MVP, Dagu v1, future state (`*.app.cove`). Written to `docs/musings/parleys/2026-07-06-c4-diagrams.md`. See that file for the diagrams.

Key finding from the diagrams: MVP and v1 are identical (no phasing needed within Dagu scope). The future state adds per-app provisioning (credentials, buckets, topics) but does not rearchitect the core — it extends. The topology is forward-compatible.

---

### T11: Credential bootstrapping — Vault token to snapshot Vault

**Raised:** 2026-07-06
**Status:** resolved

**Resolution:** Bootstrap credentials (Vault snapshot token, MinIO root creds) live in `compose/.env`, not in Vault. Dagu reads them as environment variables. No circular dependency — Dagu doesn't need Vault to be up to read its credentials. Dagu does routine snapshots, not disaster recovery. If Vault is down, backup fails, ntfy alerts, operator restores from last good snapshot in MinIO. Explicit failure mode, not implicit.

Separate musing written: `docs/musings/cove-secrets-in-keychain.md` — keychain replaces `.env` for all Cove secrets. Dagu sashay uses existing `.env` pattern; keychain migration is a separate sashay.

---

### T12: MinIO credentials — same bootstrapping problem

**Raised:** 2026-07-06
**Status:** resolved

Same resolution as T11. MinIO root creds in `.env`. Dagu reads them as env vars. No Vault dependency for MinIO access.

---

### T13: ntfy auth for MVP

**Raised:** 2026-07-06
**Status:** resolved

**Resolution:** Authless for MVP, with explicit note that per-topic tokens are required before any `*.app.cove` app uses ntfy. The MVP threat model is local network eavesdropping — if you're on the same WiFi, you can read ntfy topics. But you can also read all Cove HTTP traffic without TLS pinning, so ntfy isn't the weakest link. Not worth the friction (bootstrap tokens, UI auth prompts) for a single-operator localhost stack.

Also resolved: ntfy is justified, not scope creep. Forgejo can create alerts (issues, webhooks) but can't deliver push notifications to phone/desktop outside the browser. ntfy's cross-platform push (phone app, desktop PWA) fills a gap Forgejo doesn't cover.

---

### T14: DAGs — host-mounted or version-controlled?

**Raised:** 2026-07-06
**Status:** resolved (moot)

**Resolution:** This tension was based on a stale framing where Cove ships "official DAGs" (health check, backup, cert renewal) that manage Cove itself. That framing is dead — Dagu is platform infra, not a Cove manager. Cove provisions the empty `dags/` directory and the Dagu service. The operator/user writes their own DAGs. Cove never touches them. Same model as Forgejo: Cove ships the service, the user puts repos in it.

The version-control question (host-mounted vs Forgejo-synced) is a user workflow choice, not a Cove architecture decision. Some users edit DAGs directly, some sync from git. Dagu supports both. Not Cove's problem.

---

(Parley complete — all tensions resolved)