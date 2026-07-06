# Dagu as Cove's Script Scheduler

Adding [Dagu](https://github.com/dagucloud/dagu) (GPLv3, Go binary, file-backed, web UI) to the Cove compose stack alongside Forgejo Actions. Dagu is a lightweight workflow engine — single binary, no database, YAML DAGs, web UI, webhook triggers, built-in Vault secret provider, and an MCP server for AI agent integration.

Dagu is **infrastructure that provides scheduling**, not a Cove manager. It calls Cove's HTTP APIs like any other client. It does not restart Cove containers, exec into them, or manage their lifecycle.

## The Gap

Cove has no scheduler. No cron, no periodic task runner, no background job system. The health daemon musing (`docs/musings/cove-health-daemon.md`) identifies this for observability, but the gap is broader:

| Need | Current State | Dagu Fit |
|------|---------------|----------|
| Periodic maintenance (cert renewal, data cleanup, backup) | Manual `cove up` or ad-hoc cron | Cron scheduling in YAML DAGs |
| Webhook endpoints (GitHub mirror, external hooks) | Nothing | Per-DAG webhook tokens |
| Multi-step workflows (backup → verify → notify) | Nothing | YAML DAGs with dependencies, retries, approvals |
| Long-running background jobs | Nothing | Scheduler + executor in one binary |
| Secret access for scripts | Vault (manual) | Built-in Vault secret provider |
| AI agent workflow control | Nothing | Built-in MCP server |

## Boundary with Forgejo Actions

Forgejo Actions is CI/CD: build, test, deploy, triggered by `push`, `pull_request`, `schedule`. Ephemeral containers, checked out from git, reports status to PRs.

Dagu is operational scripting: periodic, event-driven, or on-demand execution of scripts that interact with infrastructure, databases, and APIs.

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

Windmill's auto-generated UIs are powerful, but Cove's ops scripts (cert renewal, backup, health check) don't need UIs — they need reliable scheduling, logging, and notifications. Dagu covers that without Postgres.

## Docker Socket: The Lethal Trifecta

Mounting the raw Docker socket into a container gives it root on the host. An attacker who compromises Dagu (or a DAG) can mount any host path into a new container, exec into any other container (including Vault), or pivot to the host. This is the documented attack path for any container with socket access — not hypothetical.

**Dagu does not get raw socket access.** Instead, a custom Docker API proxy sits between Dagu and the Docker daemon. The proxy enables Dagu's `container:` step type (spawning ephemeral tool containers) while blocking the dangerous parts.

### Docker API Proxy

~100 lines of Go. An HTTP server that proxies to the Unix socket with path/method filtering and request body sanitization.

**Allowed (ephemeral container lifecycle for `container:` steps):**
- `POST /containers/create` — **strip `Binds`, `Mounts`, `Volumes` from request body** (no host path mounts)
- `POST /containers/{id}/start`
- `POST /containers/{id}/wait`
- `GET /containers/{id}/logs`
- `DELETE /containers/{id}`
- `GET /containers/json` — filtered to containers with a `dagu-` prefix
- `GET /images/json` — list available images
- `POST /images/{name}/tag` — tag images

**Blocked (everything else):**
- `POST /containers/{existing}/restart` or `/stop` — can't touch existing containers
- `POST /containers/{existing}/exec` — can't exec into running containers
- `POST /containers/create` with `Binds`/`Mounts` — can't mount host paths (the lethal trifecta vector)
- `POST /images/create` — can't pull arbitrary images (only pre-pulled or from Cove registry)
- `GET /containers/json` for non-`dagu-` containers — can't enumerate other containers
- Everything else: 403

The key defense is stripping mounts from create requests. A compromised Dagu can spawn a container with `alpine:3.21` and `curl`, but it can't mount `/` or `/etc` or `~/.ssh` into it. The host-path-to-root attack chain is broken.

```yaml
# compose
dagu:
  volumes:
    - ~/Documents/cove-data/dagu:/data
    # NO raw socket mount
  environment:
    DOCKER_HOST: tcp://docker-proxy:2375  # talk to proxy, not socket

docker-proxy:
  build: ./docker-proxy
  container_name: cove-docker-proxy
  volumes:
    - /var/run/docker.sock:/var/run/docker.sock:ro
  networks:
    - cove
  restart: unless-stopped
  mem_limit: 16m
```

## Script Runtime: No Host Access, HTTP-Only

Dagu's `container:` step type spawns ephemeral tool containers via the proxy. These containers have **no host mounts** (stripped by the proxy). They can only reach other services via the Docker network.

| Task | How It Works | Host Access Needed? |
|------|-------------|:---:|
| Health check | `curl http://forgejo:3000/api/healthz` | No |
| Vault backup | `curl -H "X-Vault-Token: ..." http://vault:8200/v1/sys/storage/raft/snapshot -o /tmp/snap` | No |
| Forgejo backup | Forgejo API `POST /api/v1/dump` | No |
| Cert expiry check | Cert fetched via Cove API, not filesystem | No |
| Notifications | Webhook/ntfy/email | No |

**Data flows via HTTP APIs, not filesystem mounts.** The proxy strips mounts, so DAGs can't read host files directly. Any data a DAG needs comes through an API endpoint. This is a deliberate constraint — it makes Dagu safe to run untrusted workflows.

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
    DOCKER_HOST: tcp://docker-proxy:2375
  volumes:
    - ~/Documents/cove-data/dagu:/data
    # NO raw socket mount — proxy only
  networks:
    - cove
  restart: unless-stopped
  mem_limit: 64m

docker-proxy:
  build: ./compose/docker-proxy
  container_name: cove-docker-proxy
  volumes:
    - /var/run/docker.sock:/var/run/docker.sock:ro
  networks:
    - cove
  restart: unless-stopped
  mem_limit: 16m
```

Key points:
- **File-backed state** under `~/Documents/cove-data/dagu/` — no database volume needed
- **No raw Docker socket** — Dagu talks to the proxy, proxy talks to the socket
- **`DAGU_HOST: 0.0.0.0`** so nginx can reach it from another container
- **64MB memory limit** — negligible next to Forgejo/Vault

## nginx Route

```
server {
    listen 443 ssl;
    server_name dag.cove;
    ssl_certificate     /certs/cove.local.pem;
    ssl_certificate_key /certs/cove.local-key.pem;
    location / {
        proxy_pass http://dagu:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## Vault Integration

Dagu has a built-in Vault secret provider. DAG steps reference secrets from Vault directly:

```yaml
steps:
  - id: backup
    run: ./backup.sh
    secrets:
      VAULT_TOKEN: vault://secret/cove/vault/token
```

Dagu connects to Vault at the internal Docker network address `http://vault:8200`.

## MCP Server

Dagu exposes a built-in MCP server at `http://dagu:8080/mcp`. AI agents (Claude Code, Codex, etc.) can inspect Dagu state, preview changes, edit workflows, and control runs.

## cove-tools Image

A custom image with the tools Dagu's DAGs need: `curl`, `openssl`, `jq`, `python3`, and potentially the `cove` CLI (if it can call Cove's HTTP API from inside a container). Built from the Cove repo and pushed to the Cove registry.

```dockerfile
FROM alpine:3.21
RUN apk add --no-cache curl openssl jq python3
# cove CLI optional — depends on whether it works without host keychain access
```

This image is used as the `container:` for steps that need tools beyond what `curlimages/curl` or `alpine` provide. Pre-pulled on `cove up` so the proxy's image-allowlist is satisfied.

## First DAGs

```yaml
# health-check.yaml
name: health-check
schedule: "* * * * *"
steps:
  - id: check_forgejo
    container:
      image: curlimages/curl:8
    run: curl -sf http://forgejo:3000/api/healthz
    retry_policy:
      limit: 2
      interval_sec: 5
    continue_on:
      failure: true
  - id: check_vault
    container:
      image: curlimages/curl:8
    run: curl -sf http://vault:8200/v1/sys/health
    retry_policy:
      limit: 2
      interval_sec: 5
    continue_on:
      failure: true
  - id: check_nginx
    container:
      image: curlimages/curl:8
    run: curl -sf https://nginx/api/healthz
    retry_policy:
      limit: 2
      interval_sec: 5
    continue_on:
      failure: true
  - id: notify_on_failure
    depends: [check_forgejo, check_vault, check_nginx]
    run: |
      if [ "$DAGU_STEP_STATUS" != "success" ]; then
        echo "Cove service degraded"
      fi
```

```yaml
# vault-backup.yaml
name: vault-backup
schedule: "0 3 * * 0"
steps:
  - id: snapshot
    container:
      image: cove-tools:latest
    run: |
      # Fetch Vault token from Dagu's secret store
      TOKEN="${VAULT_TOKEN}"
      # Snapshot via HTTP API — no docker exec, no host access
      curl -sf \
        -H "X-Vault-Token: $TOKEN" \
        http://vault:8200/v1/sys/storage/raft/snapshot \
        -o /tmp/vault-snapshot.snap
      # Upload to backup target (S3, local MinIO, or Forgejo releases)
      echo "Snapshot saved"
    secrets:
      VAULT_TOKEN: vault://secret/cove/vault/token
```

```yaml
# cert-check.yaml
name: cert-check
schedule: "0 6 * * *"
steps:
  - id: check_expiry
    container:
      image: cove-tools:latest
    run: |
      # Fetch cert via Cove's API (not filesystem — proxy blocks host mounts)
      # If Cove exposes a cert status endpoint, use it
      # Otherwise, openssl s_client against the live endpoint
      echo | openssl s_client -connect nginx:443 2>/dev/null \
        | openssl x509 -enddate -noout 2>/dev/null \
        | cut -d= -f2
    continue_on:
      failure: true
```

### Key Design Constraints

1. **No host filesystem access.** The proxy strips all mounts from container create requests. DAGs cannot read `~/Documents/cove-data/` directly. All data flows via HTTP APIs.
2. **No `docker exec` into existing containers.** The proxy blocks exec on non-`dagu-` containers. Dagu can't reach into Vault or Forgejo containers.
3. **No container restart/stop.** The proxy blocks lifecycle operations on existing containers. Dagu can't restart Cove services.
4. **Image allowlist.** The proxy blocks `POST /images/create`. Only pre-pulled images (cove-tools, curlimages/curl, alpine) are available. `cove up` pre-pulls them.
5. **DAGs interact with Cove via HTTP APIs** — Forgejo REST API, Vault HTTP API, nginx health endpoints. Not via Docker.

## What This Means for the Health Daemon Musing

Dagu does **not** replace the health daemon. The health daemon musing proposed a process that restarts failed containers. Dagu can't do that — it can only detect and notify. Container recovery stays with `restart: unless-stopped` in Compose and a host-side launchd watchdog for hung states. Dagu's role is observability and alerting, not self-healing.

## Reusability: cove-tools in Other Contexts

The `cove-tools` image and the Docker API proxy are general-purpose infrastructure. They could serve:

- **swain-box**: opencode instances in a sandbox could use `cove-tools` as a `container:` step image for running ops scripts against Cove APIs. The proxy pattern applies if swain-box runs Docker inside the VM.
- **Any Dagu-like scheduler**: the proxy is not Dagu-specific. Any tool that needs ephemeral container spawning without host access can use it.

The constraint that makes this portable: **no host access, HTTP-only**. The image and proxy work anywhere there's a Docker daemon and a network.

## Ansible Provisioning

- Add `dagu` and `docker-proxy` services to docker-compose.yml template
- Add `dag.cove` to nginx config template
- Create `~/Documents/cove-data/dagu/` directory
- Seed initial DAG YAML files to `~/Documents/cove-data/dagu/dags/`
- Pre-pull tool images: `curlimages/curl:8`, `alpine:3.21`, `cove-tools:latest`
- Build `cove-tools` image and push to Cove registry
- Build `docker-proxy` image
- Add `dag.cove` to `cove status` health checks

## Open Questions

1. **DAG storage path?** Mount `~/Documents/cove-data/dagu/dags/` into the container. Cove seeds the initial DAGs, operator edits freely.
2. **Auth for dag.cove?** `DAGU_AUTH_MODE: none` behind nginx (which terminates TLS) is fine for single-operator. Switch to `builtin` (JWT/RBAC) if exposed beyond localhost.
3. **Dagu version pinning?** Pin to a specific tag in docker-compose.yml rather than `latest` for stability.
4. **Proxy implementation?** Go HTTP server with path/method allowlist + request body sanitization (strip mounts). ~100 lines. Could be a separate repo or a directory in the Cove compose tree.
5. **Cert renewal without filesystem access?** If Dagu can't write to `~/Documents/cove-data/certs/`, cert renewal needs to happen via a Cove API endpoint (`POST /api/certs/renew`) or a host-side process triggered by webhook from Dagu.
6. **Backup storage without filesystem access?** Vault snapshots can't be written to `~/Documents/cove-data/backups/` from Dagu. Options: upload to Forgejo releases, S3-compatible storage, or a Cove backup API endpoint.

## Next Steps

1. Build the Docker API proxy (~100 lines of Go)
2. Build `cove-tools` image (Alpine + curl + openssl + jq + python3)
3. Add `dagu` + `docker-proxy` to the compose stack and `cove up`
4. Write the 3 DAGs above (health check, vault backup, cert check)
5. Add `dag.cove` to nginx config and `cove status`
6. Write the Ansible provisioning playbook
7. If Dagu passes evaluation, write a plan for integration

---

## Appendix: Why Not Windmill

Windmill was the first candidate. It's powerful — auto-generated UIs, visual flow editor, multi-language sandboxed execution, webhook-to-script. But it requires Postgres, which is a heavy dependency for a single-developer stack. The cost-benefit analysis:

- **Postgres:** +1 service, ~200MB image, ~300MB memory, backup burden, schema migrations on every upgrade
- **Auto-generated UIs:** Nice, but Cove's ops scripts don't need UIs. They need reliable scheduling and logging.
- **Visual flow editor:** Overkill for 3-step DAGs (backup → verify → notify).
- **Multi-language sandboxing:** All Cove ops scripts are shell commands. No need for Python/TS/Go sandboxes.

Dagu covers the 90% use case with zero infrastructure overhead. The 10% Windmill offers (UIs, flow editor, sandboxing) isn't worth Postgres for a single-dev stack.