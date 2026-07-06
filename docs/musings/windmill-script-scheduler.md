# Dagu as Cove's Script Scheduler

Adding [Dagu](https://github.com/dagucloud/dagu) (GPLv3, Go binary, file-backed, web UI) to the Cove stack alongside Forgejo Actions. Dagu is a lightweight workflow engine — single binary, no database, YAML DAGs, web UI, webhook triggers, built-in secret management with Vault support, and an MCP server for AI agent integration.

This started as a Windmill evaluation (see below), but Dagu won on weight: no Postgres, no new runtime, no SRE tax.

## The Gap

Cove has no scheduler. No cron, no periodic task runner, no background job system. The health daemon musing (`docs/musings/cove-health-daemon.md`) identifies this for observability, but the gap is broader:

| Need | Current State | Dagu Fit |
|------|---------------|----------|
| Periodic maintenance (cert renewal, data cleanup, backup) | Manual `cove up` or ad-hoc cron | Cron scheduling in YAML DAGs |
| Webhook endpoints (GitHub mirror, external hooks) | Nothing | Per-DAG webhook tokens |
| Multi-step workflows (backup → verify → notify) | Nothing | YAML DAGs with dependencies, retries, approvals |
| Long-running background jobs | Nothing | Scheduler + executor in one binary |
| Secret access for scripts | Vault (manual) | Built-in secret mgmt with Vault provider |
| AI agent workflow control | Nothing | Built-in MCP server |

## Boundary with Forgejo Actions

Forgejo Actions is CI/CD: build, test, deploy, triggered by `push`, `pull_request`, `schedule`. Ephemeral containers, checked out from git, reports status to PRs.

Dagu is operational scripting: periodic, event-driven, or on-demand execution of scripts that interact with infrastructure, databases, and APIs.

**Boundary:** "Does this need to report back to a PR or commit status?" → Actions. "Does this need a schedule, webhook, or web UI?" → Dagu.

## Why Dagu Over Windmill

| Factor | Windmill | Dagu |
|--------|----------|------|
| Database | Postgres required | None (file-backed) |
| Binary size | Multi-service (Rust + Svelte) | Single Go binary (~30MB) |
| Memory | ~500MB (windmill + postgres) | ~50MB |
| Setup | 3 files (compose, caddy, .env) | `brew install dagu` |
| Vault integration | Custom resource types | Built-in Vault provider |
| MCP server | No | Built-in |
| License | AGPLv3 + proprietary features | GPLv3 |
| Auto-generated UIs | Yes (Windmill's killer feature) | No (typed param forms only) |

For a single-dev stack, Windmill's auto-generated UIs are the main thing you lose. But Cove's ops scripts (cert renewal, backup, health check) don't need UIs — they need reliable scheduling, logging, and notifications. Dagu covers that with zero infrastructure overhead.

## Architecture Impact

### No New Database

Dagu is file-backed. State, logs, and queue live under `~/.local/share/dagu/` by default. No Postgres, no Redis, no new container. This is the decisive advantage over Windmill.

### Deployment: Native Binary, Not Docker

Dagu runs as a native binary on the host, not in a container. This is actually better for Cove's use case — Dagu needs access to the Docker socket to restart containers (health daemon), and to the filesystem for backups. Running it as a launchd service on macOS is the natural fit.

```
brew install dagu
dagu start-all --port 8080
```

Or via the installer script:
```
curl -fsSL https://raw.githubusercontent.com/dagucloud/dagu/main/scripts/installer.sh | bash
```

### nginx Route

```
dag.cove → host:8080
```

Dagu binds to `127.0.0.1:8080` by default. nginx proxies `dag.cove` to it, same pattern as other Cove services.

### Vault Integration

Dagu has a built-in Vault secret provider. DAG steps can reference secrets from Vault directly — no manual export, no env file. This is a first-class feature, not an afterthought.

```yaml
# dagu DAG referencing Vault secrets
steps:
  - id: backup
    run: ./backup.sh
    secrets:
      VAULT_TOKEN: vault://secret/cove/vault/token
      AWS_ACCESS_KEY_ID: vault://secret/cove/backup/aws_access_key
```

### MCP Server

Dagu exposes a built-in MCP server at `http://localhost:8080/mcp`. AI agents (Claude Code, Codex, etc.) can inspect Dagu state, preview changes, edit workflows, and control runs. This is relevant for Cove's agent-driven workflow — the operator's AI tools can manage Dagu workflows directly.

## Relationship to Health Daemon

The health daemon musing proposes a Python background process. Dagu can *be* the health daemon: a scheduled DAG that runs every 60s, checks each service's health endpoint, and restarts failed containers via the Docker API. The DAG has retry policies, notifications, and a web UI for history.

But Dagu itself needs a system-level watchdog. If Dagu crashes, scheduled health checks stop. A launchd plist running `dagu start-all` with `KeepAlive` handles this — macOS restarts Dagu automatically. This is the same pattern as the health daemon musing's "system-level watchdog" recommendation, just with Dagu as the richer runtime on top.

**Architecture:**
- launchd: restarts Dagu if it crashes (KeepAlive)
- Dagu: runs health check DAG every 60s, restarts failed containers
- Dagu web UI: history, logs, manual controls

## Implementation Sketch

### macOS: launchd Service

```xml
<!-- ~/Library/LaunchAgents/com.cove.dagu.plist -->
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.cove.dagu</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/dagu</string>
        <string>start-all</string>
        <string>--port=8080</string>
    </array>
    <key>KeepAlive</key>
    <true/>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>~/Documents/cove-data/dagu/stdout.log</string>
    <key>StandardErrorPath</key>
    <string>~/Documents/cove-data/dagu/stderr.log</string>
</dict>
</plist>
```

### nginx Route

```
server {
    listen 443 ssl;
    server_name dag.cove;
    ssl_certificate     /certs/cove.local.pem;
    ssl_certificate_key /certs/cove.local-key.pem;
    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### First DAGs

```yaml
# ~/.config/dagu/dags/health-check.yaml
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
    run: curl -sf https://git.cove/api/healthz
    retry_policy:
      limit: 2
      interval_sec: 5
    continue_on:
      failure: true
  - id: notify_on_failure
    depends: [check_forgejo, check_vault, check_nginx]
    run: |
      if [ "$DAGU_STEP_STATUS" != "success" ]; then
        osascript -e 'display notification "Cove service degraded" with title "Cove Health"'
      fi
```

```yaml
# ~/.config/dagu/dags/cert-renewal.yaml
name: cert-renewal
schedule: "0 6 * * *"  # daily at 6am
steps:
  - id: check_expiry
    run: |
      EXPIRY=$(openssl x509 -enddate -noout -in ~/Documents/cove-data/certs/cove.local.pem | cut -d= -f2)
      EXPIRY_EPOCH=$(date -j -f "%b %d %H:%M:%S %Y" "$EXPIRY" +%s)
      NOW=$(date +%s)
      DAYS_LEFT=$(( (EXPIRY_EPOCH - NOW) / 86400 ))
      echo "days_left=$DAYS_LEFT"
      [ "$DAYS_LEFT" -lt 7 ]
    continue_on:
      failure: true  # skip renewal if cert is fresh
  - id: renew
    depends: [check_expiry]
    run: cove certs renew
  - id: restart_nginx
    depends: [renew]
    run: docker compose -f ~/Documents/code/cove/compose/docker-compose.yml restart nginx
```

```yaml
# ~/.config/dagu/dags/vault-backup.yaml
name: vault-backup
schedule: "0 3 * * 0"  # weekly at 3am Sunday
steps:
  - id: snapshot
    run: |
      docker exec cove-vault vault operator raft snapshot export /tmp/vault-snapshot.snap
      tar czf ~/Documents/cove-data/backups/vault-$(date +%Y%m%d).tar.gz -C /tmp vault-snapshot.snap
  - id: cleanup
    depends: [snapshot]
    run: find ~/Documents/cove-data/backups -name 'vault-*.tar.gz' -mtime +90 -delete
```

### Ansible Provisioning

- Add `dag.cove` to nginx config template
- Install Dagu via brew or installer script
- Deploy launchd plist for `com.cove.dagu`
- Seed initial DAG YAML files to `~/.config/dagu/dags/`
- Add `dag.cove` to `cove status` health checks

## What You Lose vs Windmill

- **Auto-generated UIs** — Windmill's killer feature. Script params become forms automatically. Dagu has typed param forms but no app builder.
- **Visual flow editor** — Windmill's drag-and-drop flow builder. Dagu is YAML-only.
- **Multi-language script execution** — Windmill runs Python/TS/Go/Bash/SQL in sandboxed workers. Dagu runs shell commands (any language) but no sandboxing.
- **Built-in webhook-to-script** — Windmill turns any script into an HTTP endpoint. Dagu has webhook triggers but they queue a DAG run, not an HTTP response.

None of these matter for Cove's use cases. The ops scripts are shell commands, the workflows are simple DAGs, and the operator doesn't need a drag-and-drop editor.

## Open Questions

1. **Dagu as part of `cove up` or standalone?** Dagu runs as a launchd service, not a Docker container. `cove up` should ensure it's running (like it ensures Colima is running), but Dagu's lifecycle is independent of the compose stack.
2. **DAG storage location?** `~/.config/dagu/dags/` is the default. Should Cove manage these (like it manages compose files) or let the operator manage them directly? Cove should seed the initial DAGs but the operator edits them freely.
3. **Dagu version pinning?** `brew install dagu` gets latest. For stability, pin to a specific version in the Ansible playbook.
4. **Auth for dag.cove?** Dagu supports `builtin` auth mode (JWT, RBAC, OIDC). For single-operator, `basic` auth or even `none` behind nginx (which already terminates TLS) is sufficient. But if exposed beyond localhost, use `builtin`.
5. **Health daemon overlap?** Dagu replaces the health daemon's scheduling and notification. The launchd plist replaces the system-level watchdog. The health daemon musing's TUI at `cove status` is still useful for a rich terminal view — Dagu's web UI covers the browser, `cove status` covers the terminal.

## Next Steps

1. `brew install dagu` and run `dagu start-all` to evaluate UX
2. Write the 3 DAGs above (health check, cert renewal, vault backup) and run them for a week
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
