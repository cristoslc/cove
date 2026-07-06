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
  image: git.cove/cove/dagu:latest  # custom image, see "Script Runtime" section
  container_name: cove-dagu
  command: ["dagu", "start-all", "--port=8080", "--dags=/data/dags"]
  environment:
    DAGU_HOST: 0.0.0.0
    DAGU_PORT: 8080
    DAGU_LOG_FORMAT: json
    DAGU_AUTH_MODE: none  # behind nginx with TLS; switch to builtin if exposed
    COVE_FORGEJO_URL: http://forgejo:3000
    COVE_VAULT_URL: http://vault:8200
    VAULT_TOKEN: ${DAGU_VAULT_TOKEN}  # from Vault, not from host keychain
  volumes:
    - ~/Documents/cove-data/dagu:/data
    - ~/Documents/cove-data/certs:/data/certs:ro
    - ~/Documents/cove-data/backups:/data/backups
  networks:
    - cove
  restart: unless-stopped
  mem_limit: 64m
```

Key points:
- **No Docker socket** — the lethal trifecta (socket + untrusted content + network) is a container escape. Dagu processes untrusted input (job postings, webhooks); no socket.
- **Custom image** (`git.cove/cove/dagu:latest`) — extends upstream Dagu with `curl`, `openssl`, `bash`, `jq`, `cove` CLI. See "Script Runtime" section.
- **File-backed state** under `~/Documents/cove-data/dagu/` — no database volume needed
- **Host volumes read-only** where possible — certs read-only, backups read-write
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

## Security: No Host Docker Socket

**Hard constraint:** Dagu does not get host Docker socket access. The lethal trifecta — Docker socket + untrusted content (job postings, webhooks, external input) + network access — is a container escape. Dagu processes untrusted input; therefore no socket.

This kills several patterns from earlier drafts:

| Pattern | Status | Why |
|---------|--------|-----|
| Pattern A: per-step `container:` steps | Dead — needs socket to `docker run` | Dagu can't spawn containers without the daemon |
| `docker exec` / `docker compose restart` in DAGs | Dead — needs socket | Can't restart Cove containers from Dagu |
| Health daemon that restarts failed containers | Dead — needs socket | Can only detect, not heal |
| `docker:28-cli` image for vault backup | Dead — needs socket | Can't `docker exec` into Vault container |

**What survives:**
- HTTP-based health checks (`curl` to endpoints) — no socket needed
- Vault API calls — no socket needed
- Cert expiry checks (`openssl`) — no socket needed, if certs are mounted read-only
- Notifications (HTTP POST to ntfy/webhook) — no socket needed
- Any script that operates over HTTP/API, not over Docker

**What's lost:**
- Container restart on failure (health daemon's self-heal)
- `docker exec` into Cove containers (vault backup, forgejo admin)
- Per-step ephemeral containers (Pattern A)

### Implication: Dagu Must Be Self-Contained

Without the socket, Dagu can only run `run:` steps inside its own container. It can't spawn other containers. This means:

1. **Pattern B (custom image) is now mandatory**, not optional. The Dagu container must have `curl`, `openssl`, `bash`, and any other tools baked in. No per-step containers.
2. **Health checks work** (HTTP to endpoints), but **self-heal doesn't**. Dagu detects failure, notifies, but can't restart. A separate mechanism (launchd timer, or a tiny authenticated restart API) handles restarts.
3. **Vault backup** can't use `docker exec`. It must use the Vault HTTP API (`/v1/sys/storage/raft/snapshot`) instead — which is the right way anyway.
4. **Cert renewal** can write new certs to a mounted volume, but can't restart nginx. A file watcher or nginx's `nginx -s reload` via a separate signal handles the reload.

### Alternative: Dagu in a VM (swain-box pattern)

If Dagu needs Docker step execution (Pattern A) or container restart capability, it goes in a VM — same isolation model as swain-box. The VM has its own Docker daemon; the host socket is never exposed. Dagu in the VM can't restart host containers (different kernel), but it can run its own containerized steps safely.

This is the cleanest answer if Dagu's workload includes untrusted content: **isolate at the VM boundary, not the container boundary.** A container with socket access is one escape away from host compromise. A VM with its own Docker daemon is one kernel boundary away from safety.

## Script Runtime: The Container-Within-Container Problem

Dagu runs inside a Docker container. The `ghcr.io/dagucloud/dagu` image ships Alpine + the Dagu binary — no `curl`, no `openssl`, no `docker` CLI, no `cove` command. Every DAG step that references host tools or host paths needs a strategy.

### The Socket Constraint Changes Everything

Without host Docker socket access (see "Security" section above), Dagu can't spawn per-step containers. Pattern A (per-step ephemeral containers) is dead. The only viable approach is **Pattern B: a custom Dagu image** with all tools baked in.

### Custom Dagu Image (Mandatory)

Extend the Dagu image with the tools Cove scripts need:

```dockerfile
FROM ghcr.io/dagucloud/dagu:latest
RUN apk add --no-cache curl openssl bash jq
# cove CLI — installed from the Cove registry or copied from a build stage
COPY --from=ghcr.io/cove/cli:latest /usr/local/bin/cove /usr/local/bin/cove
```

Build this in the Cove repo's compose pipeline so it stays in sync with the `cove` CLI version. Push to the Cove Forgejo registry. Tag with the `cove` version.

This image is the single source of truth for "what tools does Dagu need." If it also serves opencode instances in a sandbox (see "cove-tools" section below), it becomes a shared artifact across both projects.

### Data Sharing Between Steps

Without per-step containers, all steps run inside the Dagu container via `run:`. Data persists naturally between steps — no volume juggling needed. The Dagu container mounts host volumes once in its compose definition, and all steps inherit them.

### What the DAGs Look Like Now

DAGs use `run:` steps only. No `container:` steps. Tools come from the custom image.

## First DAGs (No Socket, Run-Only)

All steps run inside the Dagu container via `run:`. Tools come from the custom image. No `container:` steps, no Docker socket, no `docker exec`.

```yaml
# health-check.yaml
name: health-check
schedule: "* * * * *"
steps:
  - id: check_forgejo
    run: curl -sf http://forgejo:3000/api/healthz
    retry_policy:
      limit: 2
      interval_sec: 5
    continue_on:
      failure: true
  - id: check_vault
    run: curl -sf http://vault:8200/v1/sys/health
    retry_policy:
      limit: 2
      interval_sec: 5
    continue_on:
      failure: true
  - id: check_nginx
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
    run: |
      EXPIRY=$(openssl x509 -enddate -noout -in /data/certs/cove.local.pem | cut -d= -f2)
      EXPIRY_EPOCH=$(date -d "$EXPIRY" +%s)
      NOW=$(date +%s)
      DAYS_LEFT=$(( (EXPIRY_EPOCH - NOW) / 86400 ))
      echo "days_left=$DAYS_LEFT"
      [ "$DAYS_LEFT" -lt 7 ]
    continue_on:
      failure: true  # skip renewal if cert is fresh
  - id: renew
    depends: [check_expiry]
    run: cove certs renew --out /data/certs
  # Can't restart nginx without socket — a separate mechanism handles reload
  # (launchd watcher, or nginx -s reload via a tiny authenticated API)
```

```yaml
# vault-backup.yaml
name: vault-backup
schedule: "0 3 * * 0"
steps:
  - id: snapshot
    run: |
      # Vault HTTP API — no docker exec needed
      curl -sf -H "X-Vault-Token: ${VAULT_TOKEN}" \
        http://vault:8200/v1/sys/storage/raft/snapshot \
        -o /data/backups/vault-$(date +%Y%m%d).snap
  - id: compress
    depends: [snapshot]
    run: |
      tar czf /data/backups/vault-$(date +%Y%m%d).tar.gz \
        -C /data/backups vault-$(date +%Y%m%d).snap
      rm /data/backups/vault-$(date +%Y%m%d).snap
  - id: cleanup
    depends: [compress]
    run: find /data/backups -name 'vault-*.tar.gz' -mtime +90 -delete
```

### What Changed

1. **No `container:` steps** — everything runs in the Dagu container. Tools from the custom image.
2. **No Docker socket** — vault backup uses the HTTP API (`/v1/sys/storage/raft/snapshot`), not `docker exec`. This is the right way anyway.
3. **No container restart** — cert renewal writes new certs but can't restart nginx. A separate mechanism handles reload (see "Self-Heal Without Socket" below).
4. **Health check can't self-heal** — it detects failure, notifies, but can't restart. Self-heal needs a different mechanism.

### Self-Heal Without Socket

Dagu detects failure but can't restart. Options:

| Approach | How It Works | Complexity |
|----------|-------------|------------|
| **launchd watcher** | macOS launchd timer runs `docker compose restart <service>` based on Dagu's health output | Low — but host-level, not Dagu-level |
| **Authenticated restart API** | A tiny HTTP service (in the compose stack) that accepts a token and runs `docker compose restart`. Dagu calls it on failure. | Medium — but reintroduces the socket via a different door |
| **Docker socket proxy** | `tecnativa/docker-socket-proxy` with read-only + exec permissions only | Medium — limits socket to specific operations |
| **Just notify** | Dagu notifies the operator, operator restarts manually | Zero — acceptable for single-dev stack |

For a single-dev stack, "just notify" is the honest answer. Self-heal is a nice-to-have, not a must-have. The operator gets a notification and runs `cove restart <service>` — same as today, just faster detection.

## cove-tools: Shared Image for Dagu and swain-box

The custom Dagu image is a `cove-tools` artifact — a Docker image with the tools a Cove-aware runtime needs. If it also serves opencode instances in a swain-box sandbox, it becomes a shared asset.

### What Would Have to Be True

1. **No Docker socket in the image** — the image ships tools (`curl`, `openssl`, `bash`, `jq`, `cove` CLI), not socket access. Socket is a runtime mount, not a build-time dependency. Both Dagu and swain-box run the image without the socket.

2. **Endpoints from env vars, not hardcoded** — Dagu reaches Cove via Docker network names (`http://forgejo:3000`). swain-box reaches Cove via DNS (`https://git.cove`). The image reads `COVE_FORGEJO_URL` from env.

3. **Two profiles, one image** — the same image runs in two contexts:
   - **Host profile (Dagu)**: mounted in Cove compose, reaches services via Docker network, reads host volumes (certs, backups)
   - **Sandbox profile (opencode)**: pulled into swain-box VM, reaches Cove via DNS/Tailscale, no host volumes

4. **Vault-based auth, not file-based** — both contexts reach Vault. The image authenticates via `VAULT_TOKEN` env var, not host keychain files.

5. **No host data dependency** — the image doesn't assume `~/Documents/cove-data/` exists. Cert renewal, backup, etc. are opt-in based on mounted volumes and env vars.

If all five hold, `cove-tools` is a single build that serves both Dagu (host ops scheduling) and opencode (sandbox agent tooling). One CI pipeline, one registry entry, one version to track.

## Ansible Provisioning

- Add `dagu` service to docker-compose.yml template
- Add `dag.cove` to nginx config template
- Create `~/Documents/cove-data/dagu/` directory
- Seed initial DAG YAML files to `~/Documents/cove-data/dagu/dags/`
- Add `dag.cove` to `cove status` health checks

## Open Questions

1. **DAG storage path?** Dagu expects DAGs in a configurable directory. Mount `~/Documents/cove-data/dagu/dags/` into the container. Cove seeds the initial DAGs, operator edits freely.
2. **Auth for dag.cove?** `DAGU_AUTH_MODE: none` behind nginx (which terminates TLS) is fine for single-operator. Switch to `builtin` (JWT/RBAC) if exposed beyond localhost.
3. **Custom image build pipeline?** The `cove-dagu` image extends upstream Dagu with tools + `cove` CLI. Build it in the Cove repo's CI, push to the Cove Forgejo registry. Stay in sync with `cove` CLI version.
4. **Self-heal mechanism?** Dagu can detect failure but can't restart (no socket). Options: launchd watcher, authenticated restart API, or "just notify." For single-dev, "just notify" is honest.
5. **Dagu version pinning?** Pin the upstream Dagu version in the custom Dockerfile, not `latest`. Rebuild when upgrading.
6. **VM isolation for untrusted workloads?** If Dagu needs to run untrusted content (job posting parsing, external webhook payloads) with container spawn capability, it goes in a VM (swain-box pattern), not in the host compose stack. The host Dagu handles only trusted ops scripts (cert renewal, backup, health check).

## Next Steps

1. Build the `cove-dagu` custom image (Dockerfile + CI to push to Forgejo registry)
2. Add Dagu to the compose stack (no socket) and `cove up`
3. Write the 3 DAGs above (health check, cert renewal, vault backup) — all run-only, no container steps
4. Add `dag.cove` to nginx config and `cove status`
5. Write the Ansible provisioning playbook
6. Evaluate whether `cove-dagu` image can also serve as `cove-tools` for swain-box opencode instances
7. If Dagu passes evaluation, write a plan for integration

---

## Appendix: Why Not Windmill

Windmill was the first candidate. It's powerful — auto-generated UIs, visual flow editor, multi-language sandboxed execution, webhook-to-script. But it requires Postgres, which is a heavy dependency for a single-developer stack. The cost-benefit analysis:

- **Postgres:** +1 service, ~200MB image, ~300MB memory, backup burden, schema migrations on every upgrade
- **Auto-generated UIs:** Nice, but Cove's ops scripts don't need UIs. They need reliable scheduling and logging.
- **Visual flow editor:** Overkill for 3-step DAGs (backup → verify → notify).
- **Multi-language sandboxing:** All Cove ops scripts are shell commands. No need for Python/TS/Go sandboxes.

Dagu covers the 90% use case with zero infrastructure overhead. The 10% Windmill offers (UIs, flow editor, sandboxing) isn't worth Postgres for a single-dev stack.
