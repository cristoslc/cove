# Trove: colima-lima-gui-tools

## Key Findings

The Colima/Lima ecosystem has several GUI tools that fill the gap left by Docker Desktop's licensing changes. They range from full-featured desktop apps to lightweight terminal UIs and web-based dashboards.

### Desktop GUI Apps (Tauri-based)

**ColimaUI** (`vnknowledge2014/colima-ui`) is the most feature-rich option — Docker container management, Kubernetes resource browser, Lima VM management, AI-powered diagnostics with a self-learning knowledge bank, integrated terminal, and a dual-mode architecture (native desktop + web UI on port 11420). Built with Tauri v2, React 19, and Rust. Active development (60+ commits).

**0ma** (`chenhunghan/0ma`) is a ~15 MB Tauri app focused on Lima instance and Kubernetes management. One-click Docker & K8s setup, built-in terminal with tabs and split panes, visual Lima YAML editor. Homebrew installable. 543 commits, active.

**Nookat** (`nookat-io/nookat`) is a cross-platform (macOS, Linux, Windows) container management tool that auto-installs Colima as the default container engine. Covers containers, images, networks, and volumes. 374 commits.

**Sailor Desktop** (`stoutput/sailor-desktop`) offers a polished container dashboard grouped by compose project, network topology visualization, in-container terminal, and stats monitoring. Homebrew cask installable.

**Colima GUI** (`kyletaylored/colima-gui`) is a minimal Tauri app for basic Colima instance management (start/stop/restart/delete). 46 stars, limited functionality.

### Qt-based Desktop App

**Lima GUI** (`afbjorklund/lima-gui`) is a Qt/C++ system tray application for Lima VM management. Create/start/stop/delete VMs from templates. 243 stars, 228 commits. Supports Kvantum themes, optional terminal and VNC client. More mature than most Tauri alternatives.

### Web-based / Terminal UI

**Portainer** is the most popular web-based Docker management UI and is commonly paired with Colima as a direct Docker Desktop GUI replacement. Runs as a container itself. Supports Docker, Swarm, and Kubernetes. The "Colima + Portainer" combo is a well-documented pattern in the developer community.

**Lazydocker** is a Go-based terminal UI ("htop for Docker") that provides a live, navigable dashboard with single-keypress operations and mouse support. Lighter than Portainer, no background services.

### Menu Bar Integration

**Lima xbar Plugin** (`unixorn/lima-xbar-plugin`) provides macOS menu bar control for Lima VMs — start/stop/status only. 141 stars.

## Points of Agreement

- All tools agree that Colima/Lima provide a superior runtime to Docker Desktop (lower resource usage, no licensing fees).
- Tauri is the dominant framework for new desktop GUI tools in this space (5 of 6 desktop apps use it).
- The "Colima + Portainer" combination is the most common pattern for replacing Docker Desktop's GUI.
- No single tool has achieved dominant adoption — the ecosystem is fragmented.

## Points of Disagreement

- **Desktop vs web vs TUI**: ColimaUI and 0ma offer native desktop experiences; Portainer is web-based; Lazydocker is terminal-only. Each approach has trade-offs in resource usage, accessibility, and feature depth.
- **Feature scope**: ColimaUI aims to be an all-in-one replacement (Docker + K8s + VMs + AI). Others focus on narrower scopes (0ma on Lima/K8s, Nookat on basic container ops).

## Gaps

- No tool provides the exact same integrated experience as Docker Desktop (single app with settings, tray icon, resource graphs, and one-click setup).
- Windows support is limited — only Nookat supports it.
- No tool offers native Docker Compose visualization comparable to Docker Desktop's compose UI.
- Most tools are early-stage (pre-v1.0) with small communities.
- No tool integrates Docker Scout or vulnerability scanning.
- No tool provides Docker Desktop's extensions marketplace.
