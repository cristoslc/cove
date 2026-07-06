# Windmill as Cove's Script Scheduler

Adding [Windmill](https://github.com/windmill-labs/windmill) (AGPLv3, Rust backend, Svelte 5 frontend, Postgres) to the Cove stack alongside Forgejo Actions. Windmill turns scripts into scheduled jobs, webhook endpoints, workflows, and auto-generated UIs. Forgejo Actions handles CI/CD triggered by git events. They overlap at the edges but target fundamentally different use cases.

## The Gap Windmill Fills

Cove currently has no scheduler. No cron, no periodic task runner, no background job system. The health daemon musing (`docs/musings/cove-health-daemon.md`) identifies this gap for observability, but the gap is broader:

| Need | Current State | Windmill Fit |
|------|---------------|-------------|
| Periodic maintenance (cert renewal, data cleanup, backup) | Manual `cove up` or ad-hoc cron | Schedule scripts with cron expressions |
| Webhook endpoints (GitHub mirror, external service hooks) | Nothing | Scripts become HTTP endpoints automatically |
| Internal tool UIs (admin panels, dashboards) | Nothing | Auto-generated UIs from script params |
| Multi-step workflows (backup → verify → notify) | Nothing | Visual flow editor, script chaining |
| Long-running background jobs | Nothing | Worker pulls jobs from Postgres queue |
| Secret access for scripts | Vault (manual) | Windmill's own K/V store per workspace, or integrate with Vault |

## Boundary with Forgejo Actions

Forgejo Actions is CI/CD: build, test, deploy, triggered by `push`, `pull_request`, `schedule`. It runs in ephemeral containers, checked out from git, and reports status back to PRs. It's the right tool for:

- `npm test && npm run build` on every push
- `docker build && docker push` on tag
- Deploy to pages on push to `pages` branch

Windmill is operational scripting: periodic, event-driven, or on-demand execution of scripts that interact with infrastructure, databases, and APIs. It's the right tool for:

- Rotate TLS certs every 30 days
- Backup Vault Raft snapshots to a tarball
- Sync Forgejo mirrors from GitHub
- Health check all services and notify on failure
- Admin UI to trigger manual operations (restart service, clear cache)

**Overlap:** Both can run on `schedule`. Forgejo Actions has a `schedule` event (cron). But Actions is designed for CI pipelines, not operational scripts. The runner is ephemeral, the environment is a fresh checkout, and the output is a log in a PR. Windmill's scripts are persistent, have state, have auto-generated UIs, and can be triggered by webhooks, HTTP routes, or on-demand from a dashboard.

**Verdict:** They complement, not compete. Actions for CI/CD, Windmill for ops scripting. The boundary is: "does this need to report back to a PR or commit status?" → Actions. "Does this need a UI, a webhook, or a schedule?" → Windmill.

## Architecture Impact

### Postgres Requirement

Windmill requires Postgres. Cove currently has no Postgres — Forgejo uses SQLite, Vault uses Raft. Adding Postgres is a new service in the compose stack with persistent data under `~/Documents/cove-data/postgres/`.

This is the biggest cost. Postgres is a heavy dependency for a single-developer stack. Options:

| Approach | Pros | Cons |
|----------|------|------|
| Add Postgres container | Full Windmill, no compromises | +1 service, ~200MB image, memory overhead, backup burden |
| Use SQLite-backed alternative | No Postgres | No equivalent exists with Windmill's feature set |
| Use Forgejo Actions `schedule` event | No new service | No UIs, no webhooks, no workflow editor, no state |
| Use system cron + shell scripts | Zero new infra | No UI, no logging, no secret management, no webhooks |
| Use a lightweight scheduler (e.g., `dagu`, `jobber`) | Less overhead | No auto-generated UIs, no workflow editor, no webhook support |

**Recommendation:** If Windmill is the right tool, Postgres is worth it. But evaluate whether the use cases justify the weight. For a single-dev stack, the question is: "how many scheduled scripts will I actually write?" If the answer is 1-3 (cert renewal, backup, health check), system cron + a `cove` CLI command is simpler. If the answer is 10+ with UIs and webhooks, Windmill pays off.

### nginx Routing

Windmill's Docker Compose uses Caddy by default. Cove uses nginx. Windmill would need an nginx route:

```
windmill.cove → windmill:8000
```

Same pattern as `vault.cove` and `git.cove`. The Windmill server listens on port 8000 internally.

### Vault Integration

Windmill has its own K/V store for secrets (encrypted per workspace). Cove's source of truth is Vault. Two approaches:

1. **Use Windmill's built-in secrets** — simpler, but secrets live in two places. Windmill stores them in Postgres (encrypted). No Vault dependency for scripts.
2. **Use Vault as Windmill's secret backend** — Windmill supports resource types that could point to Vault. More complex but single source of truth.

For v1, approach 1 is pragmatic. Windmill's secrets are encrypted at rest in Postgres. If the operator wants Vault-backed secrets, that's a v2 integration.

### Identity

Windmill has its own user system (superadmin, workspaces, RBAC). For a single-operator stack, this is overkill but manageable. Default credentials (`admin@windmill.dev` / `changeme`) must be changed on first boot.

Could integrate with Forgejo OAuth in the future, but that's v2.

## Relationship to Health Daemon

The health daemon musing proposes a Python background process that polls services and self-heals. Windmill could *be* the health daemon: a scheduled script that runs every 30 seconds, checks each service's health endpoint, and restarts failed containers via the Docker API. The script would have an auto-generated UI showing current status, a history of failures, and a manual "restart all" button.

This is elegant — Windmill replaces the bespoke health daemon with a scheduled script that's visible, auditable, and triggerable from a web UI. But it's also a dependency inversion: the health daemon should be the most reliable thing in the stack. If Windmill itself is down, the health daemon can't run. A system-level watchdog (launchd plist or systemd timer) would still be needed to restart Windmill.

**Better architecture:** A lightweight system-level watchdog (launchd timer running `cove health --check` every 60s) that restarts any failed container including Windmill. Windmill then runs the richer health dashboard, history, and manual controls.

## Implementation Sketch

### Docker Compose Addition

```yaml
services:
  windmill:
    image: ghcr.io/windmill-labs/windmill:latest
    container_name: cove-windmill
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      DATABASE_URL: postgres://windmill:${WINDMILL_DB_PASSWORD}@postgres:5432/windmill
      BASE_URL: https://windmill.cove/
      MODE: standalone
    volumes:
      - ~/Documents/cove-data/windmill:/data
    networks:
      - cove
    restart: unless-stopped
    mem_limit: 256m

  postgres:
    image: postgres:16-alpine
    container_name: cove-postgres
    environment:
      POSTGRES_USER: windmill
      POSTGRES_PASSWORD: ${WINDMILL_DB_PASSWORD}
      POSTGRES_DB: windmill
    volumes:
      - ~/Documents/cove-data/postgres:/var/lib/postgresql/data
    networks:
      - cove
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U windmill"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped
    mem_limit: 256m
```

### nginx Route

```
server {
    listen 443 ssl;
    server_name windmill.cove;
    ssl_certificate     /certs/cove.local.pem;
    ssl_certificate_key /certs/cove.local-key.pem;
    location / {
        proxy_pass http://windmill:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Ansible Provisioning

- Add `windmill.cove` to nginx config template
- Generate random `WINDMILL_DB_PASSWORD`, store in Vault
- Add `windmill` and `postgres` services to docker-compose.yml template
- Post-provision: change default admin password via API

### First Scripts

1. **Health check** — poll Forgejo, Vault, nginx, dnsmasq every 60s. Log status. Notify on failure.
2. **Cert renewal** — check cert expiry daily, regenerate if < 7 days, restart nginx.
3. **Vault backup** — snapshot Raft data, tar, store to `~/Documents/cove-data/backups/`.
4. **Forgejo backup** — tar the `~/Documents/cove-data/forgejo/` directory.

## Open Questions

1. **Is Postgres worth it?** For a single-dev stack, Windmill's feature set is powerful but heavy. What's the minimum viable set of scheduled scripts that justify the dependency?
2. **Health daemon or Windmill?** Windmill could replace the health daemon, but creates a circular dependency (health daemon needs to restart Windmill). A system-level watchdog is still needed.
3. **Secret management strategy?** Windmill's built-in K/V or Vault integration? For v1, built-in is simpler. For v2, Vault as source of truth.
4. **Resource constraints?** Postgres + Windmill adds ~500MB memory and ~2GB disk. On a laptop with 16GB RAM, this is noticeable but not prohibitive.
5. **Backup strategy?** Postgres needs regular backups. Windmill stores scripts and secrets in Postgres. Losing Postgres loses all scripts and their history.
6. **Upgrade cadence?** Windmill releases frequently (v1.751.0 as of July 2026). Docker Compose makes upgrades trivial (`docker compose pull && docker compose up -d`), but schema migrations need care.
7. **Alternative: lighter scheduler?** Tools like [dagu](https://github.com/dagu-dev/dagu) (Go, DAG-based, no DB), [jobber](https://github.com/dshearer/jobber) (cron replacement), or even a simple Python scheduler in the `cove` CLI could cover the 80% case without Postgres. Evaluate before committing to Windmill.

## Next Steps

1. Run Windmill locally via its Docker Compose to evaluate UX
2. Write 3-4 scripts (health check, cert renewal, backup) to validate the workflow
3. Compare with a lighter alternative (dagu or system cron + `cove` CLI)
4. If Windmill passes evaluation, write a plan for integration
