# Trove: colima-lima-gui-tools

## Key Findings

The Colima/Lima ecosystem has a wide range of GUI tools that fill the gap left by Docker Desktop's licensing changes. They fall into three categories: native desktop apps, web-based tools (running as containers), and terminal UIs.

### Category 1: Native Desktop Apps (no Docker dependency)

These are the closest to a Docker Desktop replacement — they run as native macOS apps and don't require Docker to be running to launch.

**ColimaUI** (`vnknowledge2014/colima-ui`) is the most feature-rich option — Docker container management, Kubernetes resource browser, Lima VM management, AI-powered diagnostics with a self-learning knowledge bank, integrated terminal, and a dual-mode architecture (native desktop + web UI on port 11420). Built with Tauri v2, React 19, and Rust. Active development (60+ commits). **Security concerns: unauthenticated HTTP API, API keys in localStorage, CSP disabled.**

**0ma** (`chenhunghan/0ma`) is a ~15 MB Tauri app focused on Lima instance and Kubernetes management. One-click Docker & K8s setup, built-in terminal with tabs and split panes, visual Lima YAML editor. Homebrew installable. 543 commits, active. **Security concerns: CSP disabled + PTY spawns arbitrary commands from frontend.**

**Nookat** (`nookat-io/nookat`) is a cross-platform (macOS, Linux, Windows) container management tool that auto-installs Colima as the default container engine. Covers containers, images, networks, and volumes. 374 commits.

**Sailor Desktop** (`stoutput/sailor-desktop`) offers a polished container dashboard grouped by compose project, network topology visualization, in-container terminal, and stats monitoring. Homebrew cask installable.

**Colima GUI** (`kyletaylored/colima-gui`) is a minimal Tauri app for basic Colima instance management (start/stop/restart/delete). 46 stars, limited functionality.

### Category 2: Qt-based Desktop App

**Lima GUI** (`afbjorklund/lima-gui`) is a Qt/C++ system tray application for Lima VM management. Create/start/stop/delete VMs from templates. 243 stars, 228 commits. Supports Kvantum themes, optional terminal and VNC client. More mature than most Tauri alternatives.

### Category 3: Web-based Tools (run as Docker containers)

These tools connect to the Docker socket and provide a browser-based UI. They require Docker to be running (via Colima) but offer rich management capabilities.

**Portainer** is the most popular web-based Docker management UI and is commonly paired with Colima as a direct Docker Desktop GUI replacement. Runs as a container. Supports Docker, Swarm, and Kubernetes. The "Colima + Portainer" combo is the most well-documented pattern in the developer community.

**Dockge** (`louislam/dockge`) is a Docker Compose stack manager from the creator of Uptime Kuma. File-based approach — stores compose YAML on disk as standard files, not in a database. Focused exclusively on compose stacks. 15k+ stars. Lighter than Portainer.

**Dozzle** (`amir20/dozzle`) is a lightweight real-time log viewer. Explicitly supports Colima and Podman. No database needed. Multi-host support. 7k+ stars. Complementary to other tools — not a full management UI.

**Dockhand** (`nicedoc/dockhand`) is a modern Docker management UI with update management, pruning, scheduling, and vulnerability scanning. ~150MB RAM. Newer alternative to Portainer/Dockge.

**Yacht** (`selfhostedpro/yacht`) is a lightweight Docker management web UI focused on simplicity and app templates. Flask-based. v0.0.8, early stage. Less capable than Portainer but simpler.

### Category 4: Terminal UIs (TUI)

**Lazydocker** (`jesseduffield/lazydocker`) is a Go-based terminal UI ("htop for Docker") that provides a live, navigable dashboard with single-keypress operations and mouse support. Lighter than Portainer, no background services. Works with any Docker socket.

**ctop** (`bcicen/ctop`) is a top-like TUI for container metrics. 11k+ stars. Works with Colima via `DOCKER_HOST` env var. Known issue: the `-connector` flag doesn't accept unix socket paths directly — must set `DOCKER_HOST=unix:///$HOME/.colima/default/docker.sock`.

### Category 5: Menu Bar / Launcher Integration

**Lima xbar Plugin** (`unixorn/lima-xbar-plugin`) provides macOS menu bar control for Lima VMs — start/stop/status only. 141 stars.

**Raycast Colima Extension** provides Colima management inside Raycast — manage instances, inspect containers and images, pull and run. macOS-only (requires Raycast).

## Points of Agreement

- All tools agree that Colima/Lima provide a superior runtime to Docker Desktop (lower resource usage, no licensing fees).
- Tauri is the dominant framework for new desktop GUI tools in this space (5 of 6 desktop apps use it).
- The "Colima + Portainer" combination is the most common pattern for replacing Docker Desktop's GUI.
- No single tool has achieved dominant adoption — the ecosystem is fragmented.
- Web-based tools (Portainer, Dockge, Dozzle) all require running as a Docker container, creating a chicken-and-egg problem with Colima.

## Points of Disagreement

- **Desktop vs web vs TUI**: ColimaUI and 0ma offer native desktop experiences; Portainer/Dockge/Dozzle are web-based; Lazydocker/ctop are terminal-only. Each approach has trade-offs in resource usage, accessibility, and feature depth.
- **Feature scope**: ColimaUI aims to be an all-in-one replacement (Docker + K8s + VMs + AI). Others focus on narrower scopes (0ma on Lima/K8s, Nookat on basic container ops, Dockge on compose only, Dozzle on logs only).

## Gaps

- No tool provides the exact same integrated experience as Docker Desktop (single app with settings, tray icon, resource graphs, and one-click setup).
- Windows support is limited — only Nookat supports it.
- No tool offers native Docker Compose visualization comparable to Docker Desktop's compose UI.
- Most tools are early-stage (pre-v1.0) with small communities.
- No tool integrates Docker Scout or vulnerability scanning (Dockhand has basic scanning).
- No tool provides Docker Desktop's extensions marketplace.
- Web-based tools (Portainer, Dockge, Dozzle, Yacht, Dockhand) all require Docker to be running to launch — they can't help you if Colima itself is down.
- ctop has known compatibility issues with Colima's unix socket path.
