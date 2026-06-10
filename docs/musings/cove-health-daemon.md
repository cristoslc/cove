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

## Priority: Worth Building Soon

Cove runs constantly. The pod is 4 stable services, but "stable" doesn't mean "never crashes" — Docker Desktop updates, macOS restarts, Tailscale hiccups, and OOM kills all take down individual containers. Currently the only recovery path is noticing something broke and running `cove down && cove up` yourself. A health daemon closes that gap.

When implemented: `cli/cove/health.py` with a lightweight async loop (httpx + docker SDK), no heavy dependencies.

## Relationship to Colima Migration

The health daemon's priority is elevated by the Colima migration (`docs/musings/docker-desktop-alternatives-for-cove-pod.md`). Docker Desktop provides at-a-glance container health via its GUI; Colima is CLI-only and removes that. The health daemon is how we fill the observability gap — it should be built **before or alongside** the switch to Colima, not after.

**See also:** [`docs/musings/docker-desktop-alternatives-for-cove-pod.md`](docker-desktop-alternatives-for-cove-pod.md) — Colima is the recommended default; the daemon replaces the lost GUI feedback loop.