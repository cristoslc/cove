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
| **Nookat** | Full (containers/images/volumes/networks) | No | No | No | Medium | Unknown |
| **Sailor Desktop** | Full + compose project grouping | Yes | Yes | Yes | Low | Unknown |
| **ColimaUI** | Full + K8s + VMs + AI | Yes | Yes | Yes | Low | Worst |

### Web-based (run as containers — chicken-and-egg)

Portainer, Dockge, Dozzle, Yacht, Dockhand — all require Docker to be running. If Colima is down, they are inaccessible. This rules them out for Cove's primary use case.

### Terminal UIs

Lazydocker and ctop work via the Docker socket and are always available if Colima is up. No background services. Lightweight.

## Recommendation

**For daily Cove management: Lazydocker + `cove status` (when built)**

Lazydocker is the pragmatic choice right now:
- Works with any Docker socket, including Colima's
- No background services, no container dependency
- Live container status, logs, resource usage, restart — all in one TUI
- Single keypress operations
- ~10 MB binary, instant startup
- 30k+ stars, mature project

The health-daemon musing already proposes `cove status` as a TUI. Lazydocker fills that gap today with zero build effort.

**For a native desktop experience: Nookat**

If a GUI is preferred over terminal, Nookat is the best fit:
- Full container/image/network/volume management
- Auto-installs Colima (useful for new Cove setups)
- Cross-platform (macOS/Linux/Windows)
- No HTTP API surface (unlike ColimaUI)
- No AI features or API key storage (unlike ColimaUI)

0ma is more secure but too Lima/K8s-focused for Cove's needs. ColimaUI has the features but the security issues (unauthenticated HTTP API, localStorage API keys, CSP disabled) make it a poor fit for a platform that manages credentials and secrets.

**Not recommended for Cove:**
- ColimaUI — security issues unacceptable for a credential-managing platform
- Portainer/Dockge/Dozzle — chicken-and-egg with Colima
- Sailor Desktop — too early (4 stars, 40 commits)
- Lima GUI — VM-focused, not container-focused
