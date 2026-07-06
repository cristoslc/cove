---
title: "Parley: Dagu as Cove's Script Scheduler"
date: 2026-07-06
topic: windmill-script-scheduler
status: in_progress
---

# Parley: Dagu Revision

## Opening Position

The musing proposes adding Dagu to the Cove compose stack as a script scheduler, with a custom Docker API proxy to enable safe `container:` step spawning without the lethal trifecta of raw socket access. Dagu is positioned as infrastructure (scheduling), not a Cove manager — it calls HTTP APIs, doesn't restart containers.

The architecture is clean on paper but has a circular dependency at its core: the DAGs need to *store* their outputs (backups, cert renewals) but the proxy strips all host mounts. The musing hand-waves this as "upload to Forgejo releases, S3-compatible storage, or a Cove backup API endpoint" — none of which exist.

## Tension Backlog

1. **Output storage circular dependency** — DAGs produce data (Vault snapshots, backups) but can't write to host paths. No backup target exists. *(raising first)*
2. **Proxy complexity vs. Pattern B** — Do we need `container:` steps (and the proxy) at all, or does a custom cove-tools image with `run:` steps suffice?
3. **Health checks without recovery** — Dagu detects+notifies but can't self-heal. What's the actual value of detect-only health checks?
4. **Network egress from spawned containers** — Proxy blocks mounts but not outbound network. A compromised Dagu can exfiltrate via network.
5. **cove-tools portability claim** — Claimed reusable in swain-box, but swain-box is a VM with no Docker.
6. **Cert check fidelity** — `openssl s_client` checks the live served cert, not the stored cert file. Different failure modes.

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
**Status:** open

Dagu detects+notifies but can't self-heal (no socket access). What's the actual value of detect-only health checks? Notifications from a container can't reach macOS Notification Center. Options: ntfy webhook, email, MinIO webhook, or a Cove status API that `cove status` reads. Need to define the notification path.

---

### T4: Network egress from spawned containers

**Raised:** 2026-07-06
**Status:** resolved (moot)

No spawned containers — cove-tools runs as a single container with no socket access. Network egress is whatever Docker Compose networking allows (Cove internal network only).

---

### T5: cove-tools portability claim

**Raised:** 2026-07-06
**Status:** open

cove-tools claimed reusable in swain-box. swain-box is a VM with no Docker. For cove-tools to work there, either Docker gets installed in the VM or cove-tools ships as a native package. The image is portable; the *consumption* path isn't. Defer until swain-box actually needs it.

---

### T6: Cert check fidelity

**Raised:** 2026-07-06
**Status:** open

`openssl s_client` checks the live served cert, not the stored cert file. Different failure modes (nginx serving a stale cert vs. cert file on disk being expired). Which matters for Cove? Probably the live cert, but worth confirming.

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

(Parley in progress — tensions appended as they're raised and resolved)