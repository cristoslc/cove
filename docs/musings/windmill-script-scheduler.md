# Dagu as Cove's Script Scheduler

Adding [Dagu](https://github.com/dagucloud/dagu) (GPLv3, Go binary, file-backed, web UI) to the Cove compose stack alongside Forgejo Actions. Dagu is a lightweight workflow engine — single binary, no database, YAML DAGs, web UI, webhook triggers, built-in Vault secret provider, and an MCP server for AI agent integration.

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
    - /var/run/docker.sock:/var/run/docker.sock  # for docker exec/restart in DAGs
  networks:
    - cove
  restart: unless-stopped
  mem_limit: 64m
```

Key points:
- **File-backed state** under `~/Documents/cove-data/dagu/` — no database volume needed
- **Docker socket** mounted so DAGs can run `docker compose restart`, `docker exec`, etc.
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

Dagu has a built-in Vault secret provider. DAG steps can reference secrets from Vault directly:

```yaml
steps:
  - id: backup
    run: ./backup.sh
    secrets:
      VAULT_TOKEN: vault://secret/cove/vault/token
      AWS_ACCESS_KEY_ID: vault://secret/cove/backup/aws_access_key
```

Dagu connects to Vault at the internal Docker network address `http://vault:8200`.

## MCP Server

Dagu exposes a built-in MCP server at `http://dagu:8080/mcp`. AI agents (Claude Code, Codex, etc.) can inspect Dagu state, preview changes, edit workflows, and control runs.

## Relationship to Health Daemon

Dagu replaces the health daemon: a scheduled DAG that runs every 60s, checks each service's health endpoint, and restarts failed containers via the Docker API. The DAG has retry policies, notifications, and a web UI for history.

Dagu itself is covered by `restart: unless-stopped` in Docker Compose, same as every other Cove service. No launchd needed.

## Script Runtime: The Container-Within-Container Problem

Dagu runs inside a Docker container. The `ghcr.io/dagucloud/dagu` image ships Alpine + the Dagu binary — no `curl`, no `openssl`, no `docker` CLI, no `cove` command. Every DAG step that references host tools or host paths needs a strategy.

Three approaches:

| Approach | How It Works | Pros | Cons |
|----------|-------------|------|------|
| **Docker step** | Each step runs in a purpose-built ephemeral container via Dagu's `container:` step type | Clean isolation, right tools per step, no custom image | Container startup overhead per step (~1s), need to share data between steps |
| **Custom Dagu image** | Extend the Dagu image with `docker-cli`, `openssl`, `curl`, `cove` | Simple `run:` steps, no per-step overhead | Maintain a Dockerfile, image drifts from upstream |
| **Bind-mount host binaries** | Mount `/usr/local/bin` and `/var/run/docker.sock` | No custom image | Fragile, host-specific paths, breaks on different macOS setups |

**Recommendation: Docker step type for most things, custom image for the Dagu container itself.**

### Docker Step Pattern

Dagu supports running steps in arbitrary containers. Each step specifies its own image with the tools it needs:

```yaml
steps:
  - id: check_forgejo
    container:
      image: curlimages/curl:latest
    run: curl -sf http://forgejo:3000/api/healthz
```

This is the right pattern for Cove because:
- **Health checks** need `curl` → `curlimages/curl` (4MB)
- **Cert renewal** needs `openssl` + `cove` → custom `cove-tools` image or `alpine:latest` with `apk add openssl`
- **Vault backup** needs `docker` CLI → `docker:latest` (Docker-in-Docker image with CLI)
- **No single image** needs all tools — each step pulls only what it needs

### Data Sharing Between Steps

Dagu passes data between steps via:
- **`stdout` captured as step output** — for simple values (status, counts)
- **Artifacts** — for files (backup tarballs, reports)
- **Mounted volumes** — DAGs share the Dagu container's filesystem; Docker steps can mount the same host volumes

For the cert renewal DAG, the cert files live on the host at `~/Documents/cove-data/certs/`. The Dagu container already mounts this path. Docker steps can mount the same path with `-v`.

### Custom Dagu Image (Optional)

If per-step container overhead is annoying, build a thin extension:

```dockerfile
FROM ghcr.io/dagucloud/dagu:latest
RUN apk add --no-cache curl docker-cli openssl
COPY --from=cove-cli /usr/local/bin/cove /usr/local/bin/cove
```

But this adds maintenance burden. Start with Docker steps; only build a custom image if the overhead proves problematic.

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
# cert-renewal.yaml
name: cert-renewal
schedule: "0 6 * * *"
steps:
  - id: check_expiry
    container:
      image: alpine:3.21
    run: |
      apk add --no-cache openssl >/dev/null 2>&1
      EXPIRY=$(openssl x509 -enddate -noout -in /data/certs/cove.local.pem | cut -d= -f2)
      EXPIRY_EPOCH=$(date -d "$EXPIRY" +%s)
      NOW=$(date +%s)
      DAYS_LEFT=$(( (EXPIRY_EPOCH - NOW) / 86400 ))
      echo "days_left=$DAYS_LEFT"
      [ "$DAYS_LEFT" -lt 7 ]
    continue_on:
      failure: true
    volumes:
      - ~/Documents/cove-data/certs:/data/certs:ro
  - id: renew
    depends: [check_expiry]
    container:
      image: alpine:3.21
    run: |
      apk add --no-cache openssl >/dev/null 2>&1
      # regenerate cert — delegates to cove CLI via docker exec on the host
      # or implements cert renewal inline (openssl + python)
      echo "Cert renewal not yet implemented"
    volumes:
      - ~/Documents/cove-data/certs:/data/certs
  - id: restart_nginx
    depends: [renew]
    container:
      image: docker:28-cli
    run: docker compose -f /compose/docker-compose.yml restart nginx
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - ~/Documents/code/cove/compose:/compose:ro
```

```yaml
# vault-backup.yaml
name: vault-backup
schedule: "0 3 * * 0"
steps:
  - id: snapshot
    container:
      image: docker:28-cli
    run: |
      docker exec cove-vault vault operator raft snapshot export /tmp/vault-snapshot.snap
      tar czf /data/backups/vault-$(date +%Y%m%d).tar.gz -C /tmp vault-snapshot.snap
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - ~/Documents/cove-data/backups:/data/backups
  - id: cleanup
    depends: [snapshot]
    container:
      image: alpine:3.21
    run: find /data/backups -name 'vault-*.tar.gz' -mtime +90 -delete
    volumes:
      - ~/Documents/cove-data/backups:/data/backups
```

### Key Observations

1. **Docker step type** means each step pulls its own image. `curlimages/curl:8` is 4MB, `alpine:3.21` is 7MB, `docker:28-cli` is 20MB. After first pull, they're cached. Startup overhead is ~1s per step.
2. **Volume mounts** are per-step in Dagu's Docker step type. Each step that needs access to host files (certs, backups, compose files) must declare its own volumes.
3. **`cove` CLI** is not available inside any container. Cert renewal either needs a custom image with `cove` baked in, or the DAG implements cert renewal inline (openssl commands + Python from the `cryptography` library). The latter is more portable.
4. **`docker` CLI** in the `docker:28-cli` image talks to the host's Docker daemon via the mounted socket. `docker compose` works because the compose file is mounted at `/compose`.

## Ansible Provisioning

- Add `dagu` service to docker-compose.yml template
- Add `dag.cove` to nginx config template
- Create `~/Documents/cove-data/dagu/` directory
- Seed initial DAG YAML files to `~/Documents/cove-data/dagu/dags/`
- Add `dag.cove` to `cove status` health checks

## Open Questions

1. **DAG storage path?** Dagu expects DAGs in a configurable directory. Mount `~/Documents/cove-data/dagu/dags/` into the container. Cove seeds the initial DAGs, operator edits freely.
2. **Auth for dag.cove?** `DAGU_AUTH_MODE: none` behind nginx (which terminates TLS) is fine for single-operator. Switch to `builtin` (JWT/RBAC) if exposed beyond localhost.
3. **Docker socket security?** Dagu has access to the Docker socket for `docker exec` and `docker compose restart`. This is necessary for the health daemon use case. Same pattern as Portainer, Watchtower, etc.
4. **Dagu version pinning?** Pin to a specific tag in docker-compose.yml rather than `latest` for stability.

## Next Steps

1. Add Dagu to the compose stack and `cove up`
2. Write the 3 DAGs above (health check, cert renewal, vault backup)
3. Add `dag.cove` to nginx config and `cove status`
4. Write the Ansible provisioning playbook
5. If Dagu passes evaluation, write a plan for integration

---

## Appendix: Why Not Windmill

Windmill was the first candidate. It's powerful — auto-generated UIs, visual flow editor, multi-language sandboxed execution, webhook-to-script. But it requires Postgres, which is a heavy dependency for a single-developer stack. The cost-benefit analysis:

- **Postgres:** +1 service, ~200MB image, ~300MB memory, backup burden, schema migrations on every upgrade
- **Auto-generated UIs:** Nice, but Cove's ops scripts don't need UIs. They need reliable scheduling and logging.
- **Visual flow editor:** Overkill for 3-step DAGs (backup → verify → notify).
- **Multi-language sandboxing:** All Cove ops scripts are shell commands. No need for Python/TS/Go sandboxes.

Dagu covers the 90% use case with zero infrastructure overhead. The 10% Windmill offers (UIs, flow editor, sandboxing) isn't worth Postgres for a single-dev stack.
