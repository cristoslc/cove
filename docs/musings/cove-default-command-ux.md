---
title: "cove Default Command UX"
created: 2026-06-13
authored-by: deepseek-v4-flash:cloud
status: Draft
---

# cove Default Command UX

What should happen when a user runs `cove` with no subcommand?

## Current Behavior

Running `cove` with no arguments shows Click's default help:

```text
Usage: cove [OPTIONS] COMMAND [ARGS]...

  Cove management CLI.

Options:
  --version   Show the version and exit.
  --help      Show this message and exit.

Commands:
  up       Bring up cove containers and provision Forgejo.
  install  Inject cove service guidance into the project or global
           Claude config.
  down     Stop cove containers.
  uninstall  Stop cove containers, remove credentials, and strip
             agent guidance.
  version  Print the CLI version.
  creds    Credential management commands.
```

This is functional but not helpful for daily use.

## The Proposal: Cove Command Center (TUI)

`cove` (no args) launches a Textual TUI — a **command center** for the Cove platform. All subcommands (`cove up`, `cove down`, `cove status`, `cove restart`, `cove logs`, `cove shell`) remain as CLI commands for scripting. The TUI is only the default for bare `cove`.

This is not a status dashboard. It is a **control panel** — tabs, live-updating panels, actionable items, and deep views into every part of the platform.

## Tab Layout

### Tab 1: Overview

The landing view. A single-screen summary of everything that matters:

```
┌─ Cove Command Center ───────────────────────────────────────────┐
│ Overview │ Containers │ Network │ Vault │ Certs │ Data │ About  │
├─────────────────────────────────────────────────────────────────┤
│ Platform: UP  (since 09:42)                                     │
│ Colima:    running  (2 CPUs / 4 GB / 8 GB disk)                 │
│                                                                  │
│  cove-forgejo  ● running  healthy   https://git.cove/           │
│  cove-nginx    ● running  healthy   *.cove                      │
│  cove-vault    ● running  healthy   unsealed                    │
│  cove-dnsmasq  ● running  healthy   DNS resolution              │
│                                                                  │
│ Endpoints:                                                       │
│  Forgejo:   https://git.cove/     ● reachable                   │
│  Vault:     https://vault.cove/   ● reachable, unsealed         │
│  Registry:  https://registry.cove/  ● reachable                  │
│  Pages:     https://pages.cove/    ● reachable                  │
│  Runner:    https://runner.cove/   ● connected, idle            │
│                                                                  │
│ Health daemon: ● running  (last check: 5s ago)                  │
│                                                                  │
│ [F1] Help  [q] Quit  [Tab] Next tab  [1-6] Jump to tab         │
└─────────────────────────────────────────────────────────────────┘
```

### Tab 2: Containers

Per-container detail with actions:

```
┌─ Cove Command Center ───────────────────────────────────────────┐
│ Overview │ Containers │ Network │ Vault │ Certs │ Data │ About  │
├─────────────────────────────────────────────────────────────────┤
│ Container: cove-forgejo                                         │
│ Status:    running (42h)   Health: healthy                       │
│ Image:     codeberg.org/forgejo/forgejo:10                       │
│ Ports:     127.0.0.1:8080->3000/tcp                             │
│ CPU:       2.3%   ████░░░░░░░░░░░░░░░░  12% of 2 cores         │
│ Memory:    128MB  ████░░░░░░░░░░░░░░░░  6% of 2 GB             │
│ Disk:      1.2GB  ████████░░░░░░░░░░░░░░  12% of 10 GB         │
│ Logs (last 20 lines):                                            │
│  2026-06-13T09:42:15 [INFO] Starting server on :3000            │
│  2026-06-13T09:42:16 [INFO] SSH server started                   │
│  2026-06-13T09:42:17 [INFO] Health check passed                  │
│  ─────────────────────────────────────────────────────────────── │
│  [r] Restart  [l] Tail logs  [s] Shell  [o] Open in browser      │
│  [↑↓] Scroll  [←→] Switch container                              │
└─────────────────────────────────────────────────────────────────┘
```

Actions per container: restart, tail logs (live stream in a panel), open shell, open in browser, view resource graphs (CPU/memory over time).

Arrow keys or `[` / `]` to cycle through containers.

### Tab 3: Network

```
┌─ Cove Command Center ───────────────────────────────────────────┐
│ Overview │ Containers │ Network │ Vault │ Certs │ Data │ About  │
├─────────────────────────────────────────────────────────────────┤
│ DNS Resolution:                                                  │
│  git.cove       → 127.0.0.1  (dnsmasq)    ✓ resolves            │
│  vault.cove     → 127.0.0.1  (dnsmasq)    ✓ resolves            │
│  registry.cove  → 127.0.0.1  (dnsmasq)    ✓ resolves            │
│  pages.cove     → 127.0.0.1  (dnsmasq)    ✓ resolves            │
│  runner.cove    → 127.0.0.1  (dnsmasq)    ✓ resolves            │
│                                                                  │
│ Reverse Proxy (nginx):                                           │
│  git.cove      → cove-forgejo:3000    ● active                  │
│  vault.cove    → cove-vault:8200      ● active                  │
│  registry.cove → cove-forgejo:3000    ● active                  │
│  pages.cove    → cove-nginx:8080       ● active                  │
│  runner.cove   → cove-nginx:8080       ● active                  │
│                                                                  │
│ Connectivity:                                                    │
│  Tailscale:  ● connected  (100.x.x.x)                            │
│  Internet:   ● available  (via Colima)                           │
│                                                                  │
│ [r] Restart nginx  [d] Restart dnsmasq  [t] Tailscale status     │
└─────────────────────────────────────────────────────────────────┘
```

### Tab 4: Vault

```
┌─ Cove Command Center ───────────────────────────────────────────┐
│ Overview │ Containers │ Network │ Vault │ Certs │ Data │ About  │
├─────────────────────────────────────────────────────────────────┤
│ Vault Status:                                                    │
│  Seal:     ● unsealed  (1/1 keys, auto-unseal configured)        │
│  Version:  1.18.x                                                │
│  Uptime:   42h                                                   │
│  Cluster:  standalone                                            │
│                                                                  │
│ Auth Methods:                                                     │
│  Token:    ● configured  (root token in macOS keychain)          │
│  Approle:  ● configured  (used by Forgejo runner)               │
│                                                                  │
│ Secrets:                                                         │
│  cove/forgejo/*    12 secrets  ● accessible                     │
│  cove/vault/*       3 secrets  ● accessible                     │
│  cove/runner/*      2 secrets  ● accessible                     │
│                                                                  │
│ [u] Unseal  [r] Rekey  [t] Test token  [o] Open in browser      │
└─────────────────────────────────────────────────────────────────┘
```

### Tab 5: Certificates

```
┌─ Cove Command Center ───────────────────────────────────────────┐
│ Overview │ Containers │ Network │ Vault │ Certs │ Data │ About  │
├─────────────────────────────────────────────────────────────────┤
│ TLS Certificates:                                                │
│  git.cove        ● valid  (expires 2026-09-13, 92 days)         │
│  vault.cove      ● valid  (expires 2026-09-13, 92 days)         │
│  registry.cove   ● valid  (expires 2026-09-13, 92 days)         │
│  pages.cove      ● valid  (expires 2026-09-13, 92 days)         │
│  runner.cove     ● valid  (expires 2026-09-13, 92 days)         │
│  *.cove (CA)     ● valid  (expires 2031-06-13, 5 years)         │
│                                                                  │
│ CA: mkcert (local)                                               │
│                                                                  │
│ [r] Renew all  [R] Renew selected  [v] Verify chain             │
└─────────────────────────────────────────────────────────────────┘
```

### Tab 6: Data

```
┌─ Cove Command Center ───────────────────────────────────────────┐
│ Overview │ Containers │ Network │ Vault │ Certs │ Data │ About  │
├─────────────────────────────────────────────────────────────────┤
│ Data Directories:                                                │
│  ~/Documents/cove-data/                                          │
│  ├── forgejo/       1.2 GB  ████░░░░░░░░░░░░  12%               │
│  ├── vault/         45 MB   ░░░░░░░░░░░░░░░░░   0%               │
│  ├── nginx/         12 KB   ░░░░░░░░░░░░░░░░░   0%               │
│  ├── dnsmasq/        4 KB   ░░░░░░░░░░░░░░░░░   0%               │
│  ├── registry/     890 MB  ███░░░░░░░░░░░░░░   9%               │
│  └── runner/         2 GB   ████████░░░░░░░░░░  20%              │
│                                                                  │
│  Total:  4.1 GB / 50 GB  ████████░░░░░░░░░░░░  8%               │
│  Backup:  ● Time Machine active  (last: 2026-06-13 08:00)       │
│                                                                  │
│ [b] Browse directory  [d] Disk usage details                     │
└─────────────────────────────────────────────────────────────────┘
```

### Tab 7: About

Version info, upgrade status, links, quick reference.

```
┌─ Cove Command Center ───────────────────────────────────────────┐
│ Overview │ Containers │ Network │ Vault │ Certs │ Data │ About  │
├─────────────────────────────────────────────────────────────────┤
│ Cove v0.1.0                                                      │
│                                                                  │
│ CLI commands (all work for scripting):                            │
│  cove up          Start Cove                                     │
│  cove down        Stop Cove                                      │
│  cove status      Print status (machine-readable)                │
│  cove logs <svc>  Tail logs for a service                       │
│  cove shell <svc> Open shell in a container                     │
│  cove restart <svc>  Restart a service                           │
│  cove creds       Credential management                          │
│  cove install     Inject AGENTS.md guidance                      │
│  cove uninstall   Remove Cove                                   │
│                                                                  │
│ Links:                                                           │
│  Docs:     https://cove.dev/                                     │
│  Issues:   https://git.cove/cove/cove/issues                    │
│  Source:   https://git.cove/cove/cove                            │
│                                                                  │
│ [u] Check for updates  [d] View docs                            │
└─────────────────────────────────────────────────────────────────┘
```

## What the TUI Is

- A **Cove command center** — platform-specific, not a general Docker manager
- **Tabbed** — each domain of concern gets its own view
- **Live-updating** — polls Docker and endpoints every few seconds
- **Actionable** — every tab has keybindings for relevant actions
- **Context-aware** — shows different content when Cove is down vs up

## What It Is Not

- Not a general Docker manager (no image list, volume management, network CRUD)
- Not a replacement for Lazydocker (which is a general Docker TUI)
- Not blocking scriptability (all subcommands remain)

## Honest Evaluation

### Arguments For

1. **Unified entry point** — `cove` is the Cove command. Running it bare should show you the state of your harbor. This is the most natural behavior.

2. **Cove-specific views** — Generic Docker TUIs don't know about Vault seal state, Forgejo provisioning status, cert expiry, or DNS health. A Cove TUI surfaces what matters for this platform.

3. **Discoverability** — New users see available actions without reading docs. Keybindings visible in the UI.

4. **No external dependency** — Users don't need to install Lazydocker separately for basic management. Lazydocker becomes optional (for users who want a general Docker TUI), not required.

5. **Consistent with platform identity** — "One command gives you a working platform." `cove` shows you the platform. `cove up` starts it. `cove down` stops it. Cohesive.

### Arguments Against

1. **Dependency cost** — Textual adds ~3MB. Cove CLI is currently ~200KB. However, Cove already requires Docker, Python, and uv — 3MB is noise in that context.

2. **Maintenance burden** — A good TUI is real work: keybindings, scrollback, resize, mouse support, theming, edge cases. Lazydocker has 30k stars and years of polish. Cove would own this surface area.

3. **User preference** — Some users already have a preferred Docker TUI. Cove's TUI is Cove-specific (not a Docker manager), so they're complementary, but the user might find it annoying to learn another interface.

4. **Scope creep risk** — Once you have a TUI, users will ask for more: image management, volume browsing, network inspection. The line between "Cove dashboard" and "Docker UI" blurs. Mitigation: the TUI is Cove-specific by design; general Docker operations remain in Lazydocker.

### Arguments That Are Weak

- **"Not scriptable"** — All subcommands remain. `cove status` works in scripts. `watch cove status` works fine.
- **"Startup latency"** — Textual cold start ~200ms. For a command the user types manually, this is irrelevant.
- **"Accessibility"** — Terminal emulators handle TUIs fine with screen readers. Subcommands remain for programmatic use.
- **"Breaks `watch cove`"** — `watch cove status` is the correct invocation.

## Relationship to Lazydocker

Lazydocker is a **general Docker TUI** — it shows all containers, images, volumes, networks, builds. It's useful for any Docker user.

Cove's TUI is a **Cove command center** — it shows Cove-specific health (Vault seal state, Forgejo provisioning, cert expiry, DNS resolution, data directory usage) and provides Cove-specific actions (unseal Vault, renew certs, check DNS).

They serve different purposes and are complementary. A user might:
- Use `cove` to check platform health, unseal Vault, renew certs, restart a service
- Use `lazydocker` to inspect resource usage, prune images, or manage non-Cove containers

Lazydocker is not replaced. It's the recommended general Docker TUI if the user wants one. Cove's TUI is Cove-specific.

## Decision

**TUI as default for bare `cove`.** All subcommands remain for scripting. The TUI is a Cove command center (tabbed, live-updating, actionable), not a Docker manager.

Implementation: **Textual** (Python, ~3MB). Lazy-importable so subcommands pay no startup cost. Same language as the CLI. The Cove team already knows Python.

## Related Musings

- `docker-desktop-alternatives-for-cove-pod.md` — Colima migration context
- `cove-health-daemon.md` — Automated recovery; TUI shows health daemon status
- `gui-tools-for-cove.md` — Lazydocker as general Docker TUI; Cove TUI is platform-specific complement