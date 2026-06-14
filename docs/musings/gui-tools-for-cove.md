# GUI Tools for Managing Cove

Drawing from the `colima-lima-gui-tools` trove, here is a recommendation for which tool best helps manage Cove's containers.

## Cove's Requirements

Cove runs 4 Docker containers (forgejo, nginx, dnsmasq, vault) via docker-compose. The user needs:

- At-a-glance container health (up/down/restarting)
- Log tailing per service
- Resource usage (CPU/memory)
- One-click restart of individual services
- Must work with Colima (not Docker Desktop)
- Must work when Colima is down (no chicken-and-egg with container-based UIs)

## The Contenders

### Native Desktop Apps (no Docker dependency)

| Tool | Container Mgmt | Logs | Resource Usage | Compose | Maturity | Security |
|------|---------------|------|---------------|---------|----------|----------|
| **0ma** | Limited (Lima/K8s focused) | No | No | No | Medium | Best |
| **Nookat** | Full (containers/images/volumes/networks) | No | No | No | Very Low | Unknown |
| **Sailor Desktop** | Full + compose project grouping | Yes | Yes | Yes | Very Low | Unknown |
| **ColimaUI** | Full + K8s + VMs + AI | Yes | Yes | Yes | Low | Worst |

### Web-based (run as containers — chicken-and-egg)

Portainer, Dockge, Dozzle, Yacht, Dockhand — all require Docker to be running. If Colima is down, they are inaccessible. This rules them out for Cove's primary use case.

### Terminal UIs

Lazydocker and ctop work via the Docker socket and are always available if Colima is up. No background services. Lightweight.

## Recommendation: Lazydocker

Lazydocker is the clear winner for Cove:
- **30k+ stars**, by the same author as Lazygit (60k+ stars) — mature, actively maintained
- Works with any Docker socket, including Colima's
- No background services, no container dependency, no chicken-and-egg
- Live container status, logs, resource usage, restart — all in one TUI
- Single keypress operations, mouse support
- ~10 MB Go binary, instant startup
- No API keys, no HTTP server, no attack surface

No native desktop app is mature enough for Cove. Nookat (v0.1.7, 18 stars, last release Dec 2025) is stalled. 0ma is more secure but too Lima/K8s-focused. ColimaUI has the features but the security issues (unauthenticated HTTP API, localStorage API keys, CSP disabled) make it a poor fit for a platform that manages credentials and secrets.

## Relationship to Other Musings

This musing connects two existing ones:

**`docker-desktop-alternatives-for-cove-pod.md`** — Recommends Colima as the Docker Desktop replacement. Identifies the UX gap: "Colima is CLI-only — no GUI for container logs, resource usage, or restart buttons." Lists Lazydocker as one option to fill the gap. This musing confirms Lazydocker is the right choice.

**`cove-health-daemon.md`** — Proposes a background health daemon with a `cove status` TUI. The daemon handles what Lazydocker cannot: detecting and restarting crashed containers automatically, and working when Colima itself is down. Lazydocker and the health daemon are complementary:
- **Lazydocker** for interactive management (logs, restart, resource usage when you want to look)
- **Health daemon** for automated recovery (restart on crash, notify on escalation, status when Colima is unreachable)

The health daemon's priority is still elevated by the Colima migration — Lazydocker fills the "look at things" gap, but the daemon fills the "fix things automatically" gap. Both are needed for a complete replacement of Docker Desktop's feedback loop.

**Not recommended for Cove:**
- ColimaUI — security issues unacceptable for a credential-managing platform
- Portainer/Dockge/Dozzle — chicken-and-egg with Colima
- Nookat — stalled, too early
- Sailor Desktop — too early (4 stars, 40 commits)
- Lima GUI — VM-focused, not container-focused
