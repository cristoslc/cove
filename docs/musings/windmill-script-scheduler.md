# Dagu as Cove Platform Infrastructure

Adding [Dagu](https://github.com/dagucloud/dagu) (GPLv3, Go binary, file-backed, web UI) to the Cove compose stack as **scheduling infrastructure** — a platform service available to the operator and to user apps, alongside Forgejo (git/CI), Vault (secrets), MinIO (object storage), and ntfy (notifications).

Dagu is not a Cove manager. It does not ship Cove-specific DAGs, does not restart Cove containers, does not monitor Cove health. It provides a scheduling service. The operator writes their own DAGs; user apps write their own DAGs. Cove ships the empty service and gets out of the way.

## The Threshold Crossing

Cove was a 5-service stack serving itself. Adding Dagu — a service that *runs jobs* — tips several latent needs over threshold simultaneously. These are platform capabilities Cove was too small to justify before, not Dagu dependencies:

| Capability | Service | Bootstrapped By | Available To |
|-----------|---------|----------------|-------------|
| Scheduled jobs | Dagu | Dagu itself | Cove internals, user apps |
| Object storage | MinIO | Dagu backup workflows | Cove internals, user apps |
| Push notifications | ntfy | Dagu alert workflows | Cove internals, user apps |

All three land together because they're interdependent: Dagu needs MinIO for storage and ntfy for notifications. MinIO and ntfy are co-equal platform services, not Dagu dependencies. They serve all Cove services and will serve `*.app.cove` user apps in the future.

## Boundary with Forgejo Actions

Forgejo Actions is CI/CD: build, test, deploy, triggered by `push`, `pull_request`, `schedule`. Ephemeral containers, checked out from git, reports status to PRs.

Dagu is operational scripting: periodic, event-driven, or on-demand execution of scripts that interact with infrastructure, databases, and APIs. The operator writes DAGs; Dagu schedules and runs them.

**Boundary:** "Does this need to report back to a PR or commit status?" → Actions. "Does this need a schedule, webhook, or web UI?" → Dagu.

## Why Dagu Over Windmill

| Factor | Windmill | Dagu |
|--------|----------|------|
| Database | Postgres required | None (file-backed) |
| Stack | Rust backend + Svelte frontend + Postgres | Single Go binary |
| Memory | ~500MB (windmill + postgres) | ~50MB |
| Vault integration | Custom resource types | Built-in Vault provider |
| MCP server | No | Built-in |
| License | AGPLv3 + proprietary features | GPLv3 |
| Auto-generated UIs | Yes (Windmill's killer feature) | No (typed param forms only) |

Windmill's auto-generated UIs are powerful but unnecessary for a scheduling service. Dagu covers the use case without Postgres.

## Docker Compose

```yaml
dagu:
  image: ghcr.io/dagucloud/dagu:latest
  container_name: cove-dagu
  command: ["dagu", "start-all", "--port=8080", "--dags=/data/dags"]
  environment:
    DAGU_HOST: 0.0.0.0
    DAGU_PORT: 8080
    DAGU_LOG_FORMAT: json
    DAGU_AUTH_MODE: none  # behind nginx with TLS; switch to builtin if exposed
  volumes:
    - ~/Documents/cove-data/dagu:/data
  networks:
    - cove
  restart: unless-stopped
  mem_limit: 64m

minio:
  image: minio/minio:latest
  container_name: cove-minio
  command: server /data --console-address ":9001"
  environment:
    MINIO_ROOT_USER: ${MINIO_ROOT_USER}
    MINIO_ROOT_PASSWORD: ${MINIO_ROOT_PASSWORD}
  volumes:
    - ~/Documents/cove-data/minio:/data
  networks:
    - cove
  restart: unless-stopped
  mem_limit: 256m

ntfy:
  image: binwiederhier/ntfy:latest
  container_name: cove-ntfy
  command: serve
  volumes:
    - ~/Documents/cove-data/ntfy:/data
  networks:
    - cove
  restart: unless-stopped
  mem_limit: 32m
```

Key points:
- **No Docker socket access anywhere.** Dagu has no socket, no proxy, no `container:` step type. It runs DAGs as `run:` commands inside its own container.
- **cove-tools is the Dagu image** (see below) — a custom image with the tools DAGs need. All DAG steps are `run:` commands in that image.
- **MinIO writes to disk** at `~/Documents/cove-data/minio/` — objects are real files caught by regular machine backups (Time Machine, restic, etc.). No MinIO-specific backup needed.
- **ntfy is authless for MVP** — single-operator behind TLS. Per-topic tokens required before `*.app.cove` apps use it.

## cove-tools Image

A custom Dagu image with the tools DAGs need: `curl`, `openssl`, `jq`, `python3`, `mc` (MinIO client). Built from the Cove repo and pushed to the Cove registry.

```dockerfile
FROM ghcr.io/dagucloud/dagu:latest
RUN apk add --no-cache curl openssl jq python3
# mc (MinIO client) — static binary
RUN curl -fsSL https://dl.min.io/client/mc/release/linux-amd64/mc -o /usr/local/bin/mc && chmod +x /usr/local/bin/mc
```

This image replaces the upstream Dagu image. All DAG steps run as `run:` commands inside it. No `container:` step type, no per-step ephemeral containers, no Docker socket.

## nginx Routes

```
dag.cove     → dagu:8080
s3.cove      → minio:9000
console.s3.cove → minio:9001  (MinIO web console)
notify.cove  → ntfy:8080
```

## Credential Bootstrapping

Bootstrap credentials (Vault snapshot token, MinIO root creds) live in `compose/.env`, not in Vault. Dagu reads them as environment variables. No circular dependency — Dagu doesn't need Vault to be up to read its credentials.

This is the existing `.env` pattern Cove already uses. A separate musing (`docs/musings/cove-secrets-in-keychain.md`) proposes migrating all `.env` secrets to the macOS keychain — that's a general Cove improvement, not a Dagu dependency.

## Vault Integration

Dagu has a built-in Vault secret provider. DAG steps can reference secrets from Vault directly for *runtime* secrets (app credentials, API keys). The bootstrap credentials (snapshot token, MinIO creds) are in `.env` because they can't come from Vault (circular dependency when Vault is the thing being backed up).

## MCP Server

Dagu exposes a built-in MCP server at `http://dagu:8080/mcp`. AI agents (Claude Code, Codex, etc.) can inspect Dagu state, preview changes, edit workflows, and control runs.

## What Cove Ships vs. What the User Writes

| Cove ships | User writes |
|-----------|-------------|
| The Dagu service (running, configured) | DAGs (YAML workflows) |
| The cove-tools image (tools available) | Scripts that DAGs call |
| The empty `dags/` directory | — |
| nginx routing to `dag.cove` | — |
| MinIO service at `s3.cove` | Buckets, objects |
| ntfy service at `notify.cove` | Topics, subscriptions |

Cove does not ship example DAGs, health-check DAGs, backup DAGs, or cert-renewal DAGs. Those are user workflows. The operator may choose to write DAGs that interact with Cove's APIs (Forgejo REST API, Vault HTTP API, MinIO S3 API) — that's their choice, not Cove's job.

## Relationship to Health Daemon Musing

Dagu does **not** replace the health daemon. The health daemon musing (`docs/musings/cove-health-daemon.md`) proposes a process that detects failures and restarts containers. Dagu can't restart containers — it has no Docker socket. If the operator wants health monitoring via Dagu, they write their own health-check DAG that calls Cove HTTP APIs and publishes alerts to ntfy. That's a user workflow, not Cove infrastructure.

## Future State: `*.app.cove`

The C4 diagrams at `docs/musings/parleys/2026-07-06-c4-diagrams.md` show the topology evolution:

- **Current** (5 services): nginx, Forgejo, Vault, dnsmasq, dnsproxy
- **Dagu MVP/v1** (8 services): + Dagu, MinIO, ntfy
- **Future** (`*.app.cove`): nginx routes user app subdomains to app containers; per-app provisioning creates MinIO buckets, ntfy topics+tokens, and Vault credentials

The MVP topology is forward-compatible — the future state extends it without rearchitecting the core. MinIO and ntfy serve Cove internals now, user apps later. No phasing needed within the Dagu scope.

## Ansible Provisioning

- Add `dagu`, `minio`, `ntfy` services to docker-compose.yml template
- Build `cove-tools` image (Dockerfile above) and push to Cove registry
- Add `dag.cove`, `s3.cove`, `console.s3.cove`, `notify.cove` to nginx config template
- Create `~/Documents/cove-data/{dagu,minio,ntfy}/` directories
- Generate `MINIO_ROOT_USER` and `MINIO_ROOT_PASSWORD`, add to `.env`
- Add `dag.cove`, `s3.cove`, `notify.cove` to `cove status` health checks

## Open Questions

1. **Dagu version pinning?** Pin to a specific tag in docker-compose.yml rather than `latest` for stability.
2. **ntfy auth for future state?** Authless for MVP. Per-topic tokens required before `*.app.cove` apps use ntfy. Not building this now.
3. **MinIO console exposure?** `console.s3.cove` exposes the MinIO web UI. Behind nginx TLS, authless is fine for MVP. Add auth when user apps need it.
4. **cove-tools image hosting?** Build in Cove's CI, push to Forgejo's OCI registry. Same pattern as other Cove images.

---

## Appendix: Why Not Windmill

Windmill was the first candidate. It's powerful — auto-generated UIs, visual flow editor, multi-language sandboxed execution, webhook-to-script. But it requires Postgres, which is a heavy dependency for a single-developer stack. The cost-benefit analysis:

- **Postgres:** +1 service, ~200MB image, ~300MB memory, backup burden, schema migrations on every upgrade
- **Auto-generated UIs:** Nice, but Cove's scheduling service doesn't need UIs. It needs reliable scheduling, logging, and notifications.
- **Visual flow editor:** Overkill for the YAML DAGs users will write.
- **Multi-language sandboxing:** Dagu runs shell commands (any language) without sandboxing overhead.

Dagu covers the 90% use case with zero infrastructure overhead. The 10% Windmill offers (UIs, flow editor, sandboxing) isn't worth Postgres for this stack.