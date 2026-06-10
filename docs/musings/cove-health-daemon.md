# Cove Health Daemon (Future Idea)

Periodic health checks on the Cove pod (Forgejo, Vault, nginx, dnsmasq) that alerts the user — or self-heals — when something is down.

## Observability Gap

Currently `cove up` checks health at boot (Ansible waits for Forgejo + Vault HTTP endpoints), then exits. If a container crashes an hour later, there's no mechanism to detect or recover it. `docker ps` and `docker logs` are manual.

## Desired Behavior

A background process that:
- Runs as a subprocess of `cove up` (or as a daemonized `cove watch` command)
- Polls each service's health endpoint (Forgejo `/api/healthz`, Vault `/v1/sys/health`, nginx `:443`, dnsmasq `:5353`)
- On failure: restart the container via `docker compose restart <service>`
- On repeated failure: notify the user via macOS notification
- Writes a structured health log to `~/Documents/cove-data/health.log`
- Optional: emit current status to a file for other tools to consume

## TUI Echo

The notification interface question is interesting. Options:

| Approach | Pros | Cons |
|----------|------|------|
| macOS Notification Center | Familiar, non-blocking | One-shot, no history, dismissed easily |
| Log file only | Simple, no UI code | Silent — have to remember to check |
| TUI (`cove status`) | Rich view, history, controls | Requires terminal, must be invoked |
| Menu bar app | Always visible | macOS-native dev, distribution complexity |
| System tray icon | Always visible | Cross-platform hell |

A TUI at `cove status` is the sweet spot for a solo dev: zero persistent UI, `cove up` runs the daemon in background with macOS notifications for critical alerts, and `cove status` opens a rich terminal view (service status, uptime, recent events, tail of health log) when you want to check in.

## Self-Heal Boundaries

| Condition | Action | Notify? |
|-----------|--------|---------|
| Forgejo HTTP 5xx | `docker compose restart forgejo` | Yes, after 3rd restart |
| Vault HTTP 5xx or connection refused | `docker compose restart vault` | Yes, after 3rd restart |
| nginx not responding on :443 | `docker compose restart nginx` | Yes |
| dnsmasq not responding on :5353 | `docker compose restart dnsmasq` | Yes |
| Docker daemon not reachable | Cannot self-heal | Critical notification |
| Container repeatedly crash-looping | Stop restarting, surface logs | Escalated notification |

## Not Now, But Tracked

This is a quality-of-life improvement. The pod is 4 services, all stable, run infrequently. A health daemon adds value when Cove grows (CI runners, Kaniko, Pages) or when it runs continuously as a dev server rather than on-demand.

If/when implemented: `cli/cove/health.py` with a lightweight async loop (httpx + docker SDK), no heavy dependencies.