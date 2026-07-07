# Dagu as Cove Platform Infrastructure

Adding [Dagu](https://github.com/dagucloud/dagu) (GPLv3, Go binary, file-backed, web UI) to the Cove stack as **scheduling infrastructure**. This musing began as "should we add Windmill?" and evolved through two parleys, two ADRs, and a research trove into a phased adoption plan for Dagu.

## The Threshold Crossing

Cove was a 5-service stack serving itself. Adding Dagu — a service that *runs jobs* — tips several latent needs over threshold simultaneously. These are platform capabilities Cove was too small to justify before, not Dagu dependencies:

| Capability | Service | Bootstrapped By | Available To |
|-----------|---------|----------------|-------------|
| Scheduled jobs | Dagu | Dagu itself | Cove internals, user apps |
| Object storage | MinIO | Dagu backup workflows | Cove internals, user apps |
| Push notifications | ntfy | Dagu alert workflows | Cove internals, user apps |

All three land together. MinIO and ntfy are co-equal platform services, not Dagu dependencies. They serve all Cove services and will serve `*.app.cove` user apps in the future.

## Why Dagu, Not Windmill or an Apache Project

Evaluated under ADR-016 (Two-Tier Service Adoption Rubric). Full research in `docs/troves/scheduling-orchestration-iaas/` and `docs/musings/asf-scheduling-landscape.md`.

### Windmill fails the cost-to-graduate red line

Windmill's self-hosted Community Edition has a wide feature gate — audit logs, SSO>10 users, OpenTelemetry, autoscaling, worker groups, concurrency limits, Kafka/SQS/NATS triggers are all Enterprise-only. Self-host EE starts at $120-170/mo + per-seat + per-worker. Cloud Team plan caps at 10 users, then cliffs to Enterprise.

This is exactly the n8n pattern rejected as the red line: feature-gate critical operational features behind enterprise licensing, so a project nurtured in the safe harbor can't afford to ship. Windmill also requires Postgres (heavier stack) and locks state in a proprietary schema (higher exit cost than Dagu's file-backed JSON).

### No Apache project fits Cove's niche

The ASF has no Dagu-class tool. Verified 10 ASF projects (see `docs/musings/asf-scheduling-landscape.md`):

- **Active and relevant:** Airflow (Python DAGs, multi-vendor managed tier), DolphinScheduler (visual, China-centric, needs ZK+DB)
- **Wrong category:** NiFi (data flow), SeaTunnel (ETL, needs external scheduler), YuniKorn (K8s resource scheduler)
- **Dead:** Oozie, Aurora, Liminal
- **Framework/library:** Helix, Airavata

Every ASF scheduler requires a DB, a JVM or cluster, and targets enterprise scale. The single-binary/YAML/file-backed/local-first niche is entirely unoccupied by Apache. Airflow is the governance gold standard but the wrong shape (heavyweight, code-based, DB-backed).

### Dagu clears Tier 2

| Factor | Dagu | Assessment |
|---|---|---|
| Cost-to-graduate | No feature gate — self-host = full features | ✅ Passes |
| Feature parity | GPLv3 binary is the complete product | ✅ Strong |
| Exit cost | YAML DAGs, file-backed JSON, no DB | ✅ Passes |
| Fork-safety | GPLv3 (OSI); community small but agentic-coding era lowers bar | ⚠️ Weak pass |
| Governance | Single-vendor (dagucloud), no foundation | Weak — secondary |
| Foundation/contributor path | Fails | Minor |

Residual risk is sustainability (small community), mitigated by low exit cost. Full evaluation in parley record `docs/musings/parleys/2026-07-06-dagu-essential-use-case.md` (T7).

## Boundary with Forgejo Actions

Forgejo Actions is CI/CD: build, test, deploy, triggered by `push`, `pull_request`, `schedule`. Ephemeral containers, checked out from git, reports status to PRs.

Dagu is operational scripting: periodic, event-driven, or on-demand execution of scripts that interact with infrastructure, databases, and APIs.

**Boundary:** "Does this need to report back to a PR or commit status?" → Actions. "Does this need a schedule, webhook, or web UI?" → Dagu.

## Phased Adoption (T8 Resolution)

Two shapes for where Dagu lives:

- **Shape 1 (image library):** Cove provides a `cove-dagu` image. Projects pull it into their own compose stacks, with their own repo mounted. Structural blast-radius isolation.
- **Shape 2 (shared instance):** Cove hosts one Dagu instance at `dagu.cove`. All projects' DAGs coexist. One dashboard. Blast-radius protection is only configurable, not structural.

**Decision: Shape 2 for MVP, graduate to Shape 1 when `*.apps.cove` is ready.**

### Why not Shape 1 only (skip shared MVP)?

`localhost:PORT` is hard to track across 6-12 projects. `*.apps.cove` (hyphen-based naming: `dagu-<project>.apps.cove`, single-label wildcard cert) is a platform feature that benefits all per-project services — building it for Dagu alone would be tail-wagging-the-dog. The shared `dagu.cove` MVP gives one dashboard for all scheduled work while `*.apps.cove` matures as a separate platform sashay.

### Why not Shape 2 only (no graduation)?

Projects that need file-level scripting (run `./scripts/migrate.sh` in the project dir) can't do it in the shared container without mounting all project dirs — which destroys blast-radius isolation. Shape 1 is the escape hatch for projects that outgrow API-only.

### What Dagu multitenancy is and isn't

Dagu does NOT support native multitenancy. RBAC is user-level (who can edit which DAGs), not project-level (DAGs can't isolate from each other). The `.cove/dagu/` bind-mount convention + API-only execution is the isolation mechanism, not Dagu's auth model.

## MVP: Shape 2 (Shared `dagu.cove`, API-Only)

Cove hosts one Dagu instance at `dagu.cove`. All DAGs are API-only `run:` steps using cove-tools (curl, openssl, jq, python3, mc) — trigger Forgejo Actions, read/write MinIO objects, query Vault, call service HTTP APIs. No project filesystems mounted. Blast-radius risk is contained because DAGs can't touch the filesystem — they can only call HTTP endpoints.

### Script isolation via `.cove/dagu/` bind-mount convention

Each project keeps Dagu scripts in `.cove/dagu/` (versioned with the project, reviewed in same PRs). The shared Dagu container mounts each project's `.cove/dagu/` subdir read-only at a per-project path:

```yaml
volumes:
  - /Users/cristos/Documents/code/myapp/.cove/dagu:/dags/myapp:ro
  - /Users/cristos/Documents/code/otherapp/.cove/dagu:/dags/otherapp:ro
```

This gives:
- Scripts versioned with the project (in `.cove/dagu/`, reviewed in same PRs)
- Dagu can execute them (in `dags_dir`, where Dagu looks)
- No project data access (only `.cove/dagu/` is mounted, not `src/`, `data/`, `db/`)
- No cross-project file access (each project's mount is at a distinct path)
- Read-only mount → Dagu can execute the script but can't modify it

A script that needs project files fetches them via Forgejo's raw file API: `curl -s https://git.cove/myowner/myapp/raw/branch/main/config.json`. Filesystem writes target MinIO objects (`mc cp /tmp/report.json s3/myapp-bucket/reports/`), not the project tree.

### State and indexing

Dagu's run history *is* the index — every DAG run records stdout, outputs, artifacts, and logs in the UI. For cursors/incremental positions, Dagu's `persistent_state:` per-DAG JSON object survives across runs. For manifest-style records, the DAG appends to a MinIO object (`s3/myapp-backups/index.jsonl`). No external index DB needed.

## Graduation: Shape 1 (Per-Project `cove-dagu` Images)

When `*.apps.cove` is built (hyphen-based naming: `dagu-<project>.apps.cove`, single-label wildcard cert `*.apps.cove`, dnsmasq `address=/.apps.cove/127.0.0.1`, nginx routing per project), projects that need file-level scripting pull `cove-dagu:latest` into their own compose stack.

The `.cove/dagu/` convention is stable across both shapes. When a project graduates to its own `cove-dagu` container, the same `.cove/dagu/` dir is used — just mounted read-write alongside the full project:

```yaml
volumes:
  - /Users/cristos/Documents/code/myapp:/project:rw
  - /Users/cristos/Documents/code/myapp/.cove/dagu:/dags:rw
```

Same YAML, same scripts, no migration. Exit cost is low (YAML DAGs, file-backed state, no DB).

## cove-tools Image

A custom image with the tools DAGs need: `curl`, `openssl`, `jq`, `python3`, `mc` (MinIO client). Built from the Cove repo and pushed to the Cove registry.

```dockerfile
FROM ghcr.io/dagucloud/dagu:latest
RUN apk add --no-cache curl openssl jq python3
# mc (MinIO client) — static binary
RUN curl -fsSL https://dl.min.io/client/mc/release/linux-amd64/mc -o /usr/local/bin/mc && chmod +x /usr/local/bin/mc
```

This is a general platform tools image, not "the Dagu image." It's the runtime for all API-only DAGs in the shared MVP, and the base image for per-project `cove-dagu` containers in Shape 1.

## nginx Routes (MVP)

```
dagu.cove     → dagu:8080
s3.cove       → minio:9000
console.s3.cove → minio:9001  (MinIO web console)
notify.cove   → ntfy:8080
```

## Credential Bootstrapping

Bootstrap credentials (Vault snapshot token, MinIO root creds) live in `compose/.env`, not in Vault. Dagu reads them as environment variables. No circular dependency — Dagu doesn't need Vault to be up to read its credentials.

This is the existing `.env` pattern Cove already uses. A separate musing (`docs/musings/cove-secrets-in-keychain.md`) proposes migrating all `.env` secrets to the macOS keychain — that's a general Cove improvement, not a Dagu dependency.

## Vault Integration

Dagu has a built-in Vault secret provider (token-only, no AppRole/Kubernetes auth). DAG steps can reference secrets from Vault directly for *runtime* secrets (app credentials, API keys). The bootstrap credentials (snapshot token, MinIO creds) are in `.env` because they can't come from Vault (circular dependency when Vault is the thing being backed up).

## MCP Server

Dagu exposes a built-in MCP server at `http://dagu:8080/mcp`. AI agents (Claude Code, Codex, etc.) can inspect Dagu state, preview changes, edit workflows, and control runs. Secrets are injected at runtime and masked in logs; never passed to MCP clients.

## What Cove Ships vs. What the User Writes

| Cove ships | User writes |
|-----------|-------------|
| The Dagu service (running, configured) | DAGs (YAML workflows) |
| The cove-tools image (tools available) | Scripts that DAGs call |
| The `.cove/dagu/` bind-mount convention | Per-project `.cove/dagu/` contents |
| nginx routing to `dagu.cove` | — |
| MinIO service at `s3.cove` | Buckets, objects |
| ntfy service at `notify.cove` | Topics, subscriptions |

Cove does not ship example DAGs, health-check DAGs, backup DAGs, or cert-renewal DAGs. Those are user workflows. The operator may choose to write DAGs that interact with Cove's APIs (Forgejo REST API, Vault HTTP API, MinIO S3 API) — that's their choice, not Cove's job.

## Relationship to Health Daemon Musing

Dagu does **not** replace the health daemon. The health daemon musing (`docs/musings/cove-health-daemon.md`) proposes a process that detects failures and restarts containers. Dagu can't restart containers — it has no Docker socket. If the operator wants health monitoring via Dagu, they write their own health-check DAG that calls Cove HTTP APIs and publishes alerts to ntfy. That's a user workflow, not Cove infrastructure.

## Future State: `*.apps.cove`

The C4 diagrams at `docs/musings/parleys/2026-07-06-c4-diagrams.md` show the topology evolution:

- **Current** (5 services): nginx, Forgejo, Vault, dnsmasq, dnsproxy
- **Dagu MVP/v1** (8 services): + Dagu, MinIO, ntfy
- **Future** (`*.apps.cove`): nginx routes user app subdomains to app containers; per-app provisioning creates MinIO buckets, ntfy topics+tokens, and Vault credentials; per-project `cove-dagu` containers for file-level scripting

The MVP topology is forward-compatible — the future state extends it without rearchitecting the core. MinIO and ntfy serve Cove internals now, user apps later.

## Open Questions

1. **Dagu version pinning?** Pin to a specific tag in docker-compose.yml rather than `latest` for stability.
2. **ntfy auth for future state?** Authless for MVP. Per-topic tokens required before `*.app.cove` apps use ntfy. Not building this now.
3. **MinIO console exposure?** `console.s3.cove` exposes the MinIO web UI. Behind nginx TLS, authless is fine for MVP. Add auth when user apps need it.
4. **cove-tools image hosting?** Build in Cove's CI, push to Forgejo's OCI registry. Same pattern as other Cove images.
5. **`*.apps.cove` as separate platform sashay?** Yes — it's a general platform feature (DNS, TLS, routing) that benefits all per-project services, not just Dagu. Mused separately when ready.

## Related Artifacts

- `docs/adr/adr-016-two-tier-service-adoption-rubric.md` — the rubric Dagu clears
- `docs/adr/adr-015-iaas-graduation-test.md` — superseded by ADR-016, still the test for Tier 1 (core) services
- `docs/musings/parleys/2026-07-06-dagu-revision.md` — parley #1 record (T1-T14, resolved)
- `docs/musings/parleys/2026-07-06-dagu-essential-use-case.md` — parley #2 record (T1-T8, resolved; T8 = phased adoption)
- `docs/musings/parleys/2026-07-06-c4-diagrams.md` — C4 diagrams (current, MVP/v1, future)
- `docs/musings/cove-secrets-in-keychain.md` — keychain migration musing (separate sashay)
- `docs/musings/asf-scheduling-landscape.md` — ASF project landscape research
- `docs/troves/scheduling-orchestration-iaas/` — research trove on IaaS graduation for orchestrators