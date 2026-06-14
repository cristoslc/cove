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

## User Journeys

Before designing the interface, understand what the user actually does.

### Journey 1: Quick Status Check ("Is it up?")

The 90% case. User types `cove`, wants an immediate answer. They might be about to push code, open Forgejo, or check a secret. They need to know: are all services running? Any alerts?

**Time target:** < 2 seconds from command to answer.

### Journey 2: Diagnose a Problem ("Something's broken")

User notices a service isn't working — can't push, can't reach Vault, pages not loading. They need to investigate: which service is down? What do the logs say? Can they restart it? They'll spend minutes here, scrolling logs, trying actions.

**Time target:** < 5 seconds to find the problem service, then interactive.

### Journey 3: Routine Maintenance ("I should check on things")

User hasn't looked at Cove in a while. They want to check: are certs expiring? Is disk filling up? Is Vault still healthy? They'll browse through different concerns, maybe take an action (renew certs, prune data).

**Time target:** < 10 seconds to scan all concerns.

### Journey 4: Task Execution ("I need to do a thing")

User has a specific task: unseal Vault, renew certs, restart nginx, open Forgejo. They know what they want. They need to find the action and execute it quickly.

**Time target:** < 5 seconds to find and execute.

### Journey 5: Exploration ("What can this do?")

New user or returning after an update. They want to discover capabilities. What views are available? What actions can they take? What keybindings exist?

**Time target:** help should be one keystroke away.

## Information Architecture

What does the user need to see, and how does it relate?

### Primary Concerns (always relevant)

| Concern | Data | Actions |
|---------|------|---------|
| Service health | Which containers are up/down, health check status | Restart, view logs, open shell, open in browser |
| Platform status | Is Cove up or down? How long? | Start, stop |
| Alerts | Cert expiring, Vault sealed, disk low, service down | Resolve the alert |

### Secondary Concerns (check occasionally)

| Concern | Data | Actions |
|---------|------|---------|
| Vault | Seal state, auth methods, secret count | Unseal, rekey, test token |
| Certificates | Per-cert validity, expiry dates, CA info | Renew, verify chain |
| Network | DNS resolution, proxy routes, connectivity | Restart nginx/dnsmasq |
| Data | Directory sizes, total usage, backup status | Browse, prune |
| Resources | CPU/memory per container, Colima VM stats | (read-only) |
| Runner | CI runner connectivity, job queue | (read-only) |

### Relationships

- **Service health** is the root concern — everything else depends on containers running
- **Alerts** are derived from secondary concerns (cert expiry, disk usage, Vault seal)
- **Network** depends on nginx + dnsmasq being healthy
- **Vault** depends on the vault container being healthy
- **Data** is independent but affects all services if disk fills

## UX Patterns Considered

### Pattern A: Dashboard + Drill-Down (like k9s, Grafana)

```
┌─ Cove ──────────────────────────────────────────────────────────┐
│ ● UP (42h)                                                       │
│                                                                  │
│  forgejo  ● healthy   nginx    ● healthy                         │
│  vault    ● unsealed  dnsmasq  ● healthy                         │
│                                                                  │
│  ⚠ certs expire in 7 days                                        │
│                                                                  │
│  [enter] inspect  [r] restart  [l] logs  [s] shell  [o] browser │
│  [1-4] select service  [v] vault  [c] certs  [n] network         │
│  [d] data  [?] help  [q] quit                                    │
└─────────────────────────────────────────────────────────────────┘
```

**Flow:** Overview → select service/concern → full-screen detail → Esc back to overview.

**Strengths:** Fast for Journey 1 (overview is immediate). Natural drill-down for Journey 2 (select broken service → logs → restart). Alerts visible on landing. Keyboard-driven, feels like a terminal tool.

**Weaknesses:** User must learn which key goes to which view. Detail views are modal — can't see overview while inspecting.

### Pattern B: Split Pane (like Midnight Commander, htop with detail)

```
┌─ Cove ───────────────────────────────────────────────────────────┐
│ Services          │ forgejo                                       │
│                   │                                               │
│ ● forgejo  health │ Status:  ● healthy (42h)                     │
│ ● nginx    health │ CPU:     2.3%  ████░░░░░░░░░░                │
│ ● vault    unseal │ Memory:  128MB ████░░░░░░░░░░                │
│ ● dnsmasq  health │ Disk:    1.2GB ████████░░░░░░                │
│                   │                                               │
│ ⚠ certs: 7 days   │ Logs (last 10):                              │
│                   │  2026-06-13T09:42:15 [INFO] Server started   │
│                   │  2026-06-13T09:42:16 [INFO] SSH started      │
│                   │                                               │
│ [↑↓] navigate     │ [r] restart  [l] full logs  [s] shell        │
│ [tab] switch pane │ [o] browser  [←] back to list                │
└──────────────────────────────────────────────────────────────────┘
```

**Flow:** Left pane always shows service list + alerts. Right pane shows detail for selected item. Tab switches focus between panes.

**Strengths:** Always-visible context (left pane). No modal disorientation. Good for Journey 2 (see overview while inspecting). Good for Journey 3 (browse services, detail updates as you move).

**Weaknesses:** Less space for detail (half screen). More complex to implement (two focus areas). Secondary concerns (Vault, certs, network) don't fit naturally — they're not services in the left pane.

### Pattern C: Single Scrollable Dashboard (like a status page)

```
┌─ Cove ───────────────────────────────────────────────────────────┐
│ ● UP (42h)                                                       │
│                                                                  │
│ ── Services ─────────────────────────────────────────────────── │
│  forgejo  ● healthy  (2.3% CPU, 128MB)                          │
│  nginx    ● healthy  (0.1% CPU, 8MB)                            │
│  vault    ● unsealed (0.5% CPU, 45MB)                           │
│  dnsmasq  ● healthy  (0.1% CPU, 4MB)                            │
│                                                                  │
│ ── Endpoints ────────────────────────────────────────────────── │
│  git.cove       ● reachable                                     │
│  vault.cove     ● reachable, unsealed                           │
│  registry.cove  ● reachable                                     │
│  pages.cove     ● reachable                                     │
│  runner.cove    ● connected, idle                               │
│                                                                  │
│ ── Vault ────────────────────────────────────────────────────── │
│  Seal: unsealed  Auth: token + approle   Secrets: 17            │
│                                                                  │
│ ── Certificates ─────────────────────────────────────────────── │
│  ⚠ *.cove expires in 7 days                                     │
│                                                                  │
│ ── Data ─────────────────────────────────────────────────────── │
│  Total: 4.1 GB / 50 GB (8%)  Backup: Time Machine ● active      │
│                                                                  │
│ [r] restart  [l] logs  [s] shell  [o] browser  [u] unseal      │
│ [c] renew certs  [d] data details  [?] help  [q] quit           │
└──────────────────────────────────────────────────────────────────┘
```

**Flow:** Everything on one screen. Scroll to find what you need. Keybindings for actions.

**Strengths:** No navigation learning curve. Everything visible at a glance (if it fits). Good for Journey 3 (scan all concerns). Simple to implement.

**Weaknesses:** Doesn't scale — as Cove grows, the page gets longer. No room for detail (logs, graphs). Journey 2 (diagnose) requires separate log view anyway. Feels like a static report, not a command center.

### Pattern D: Mode-Based (like vim modes or tmux windows)

```
┌─ Cove · overview ───────────────────────────────────────────────┐
│ ● UP (42h)                                                       │
│  forgejo ●  nginx ●  vault ●  dnsmasq ●                         │
│  ⚠ certs: 7 days                                                 │
│                                                                  │
│  [g] go to...  [o] overview  [s] services  [v] vault            │
│  [c] certs  [n] network  [d] data  [?] help  [q] quit           │
└─────────────────────────────────────────────────────────────────┘

┌─ Cove · vault ──────────────────────────────────────────────────┐
│ Seal: ● unsealed  Auth: token + approle  Secrets: 17            │
│  cove/forgejo/*  12 secrets  ● accessible                       │
│  cove/vault/*     3 secrets  ● accessible                       │
│  cove/runner/*    2 secrets  ● accessible                       │
│                                                                  │
│  [u] unseal  [r] rekey  [t] test token  [o] browser             │
│  [g] go to...  [esc] back to overview  [q] quit                 │
└─────────────────────────────────────────────────────────────────┘
```

**Flow:** Each concern is a named mode. Switch modes with a key or `g` (go to) command palette. Each mode has its own keybindings shown in the footer.

**Strengths:** Clean — each mode is focused on one concern. Scales well (add modes, not clutter). `g` command palette is fast for Journey 4 (type to find). Mode name in title bar gives orientation.

**Weaknesses:** Modal — user can forget which mode they're in. More keystrokes to switch between concerns. No side-by-side comparison.

### Pattern E: Overview + Command Palette (like VS Code)

```
┌─ Cove ───────────────────────────────────────────────────────────┐
│ ● UP (42h)                                                       │
│  forgejo ●  nginx ●  vault ●  dnsmasq ●                         │
│  ⚠ certs: 7 days                                                 │
│                                                                  │
│  > restart                                                       │
│    restart forgejo                                               │
│    restart nginx                                                 │
│    restart vault                                                 │
│    restart dnsmasq                                               │
│    restart all                                                   │
│                                                                  │
│  [ctrl+p] command palette  [esc] close  [?] help  [q] quit      │
└──────────────────────────────────────────────────────────────────┘
```

**Flow:** Overview always visible. `ctrl+p` opens command palette — type to filter actions. Execute action → result shown inline or in a popup.

**Strengths:** Power-user efficient (Journey 4). No need to learn keybindings — just type what you want. Overview always visible. Scales infinitely (add commands, not UI).

**Weaknesses:** Poor for Journey 2 (diagnose) — can't browse logs in a palette. Poor for Journey 3 (browse) — must know what to type. Feels less like a "command center" and more like a CLI with autocomplete.

## Recommendation: Hybrid — Overview + Modes + Command Palette

No single pattern serves all journeys well. Combine them:

**Landing: Overview mode (Journey 1, 3)**

```
┌─ Cove · overview ───────────────────────────────────────────────┐
│ ● UP (42h)                                                       │
│                                                                  │
│  forgejo  ● healthy   nginx    ● healthy                         │
│  vault    ● unsealed  dnsmasq  ● healthy                         │
│                                                                  │
│  ⚠ certs expire in 7 days                                        │
│                                                                  │
│  [enter] inspect service  [v] vault  [c] certs  [n] network     │
│  [d] data  [r] runner  [ctrl+p] commands  [?] help  [q] quit    │
└─────────────────────────────────────────────────────────────────┘
```

**Service detail: full-screen mode (Journey 2)**

```
┌─ Cove · forgejo ────────────────────────────────────────────────┐
│ ● healthy (42h)                                                  │
│                                                                  │
│  CPU:     2.3%  ████░░░░░░░░░░░░░░░░  12% of 2 cores           │
│  Memory:  128MB ████░░░░░░░░░░░░░░░░  6% of 2 GB               │
│  Disk:    1.2GB ████████░░░░░░░░░░░░░░  12% of 10 GB           │
│                                                                  │
│  Logs (live):                                                    │
│  2026-06-13T09:42:15 [INFO] Starting server on :3000            │
│  2026-06-13T09:42:16 [INFO] SSH server started                   │
│  2026-06-13T09:42:17 [INFO] Health check passed                  │
│  ─────────────────────────────────────────────────────────────── │
│  [r] restart  [l] toggle log follow  [s] shell  [o] browser     │
│  [←→] switch service  [esc] back  [ctrl+p] commands  [q] quit   │
└─────────────────────────────────────────────────────────────────┘
```

**Concern modes: Vault, Certs, Network, Data, Runner (Journey 3, 4)**

```
┌─ Cove · vault ───────────────────────────────────────────────────┐
│ ● unsealed                                                       │
│                                                                  │
│  Auth: token (keychain) + approle (runner)                       │
│                                                                  │
│  Secrets:                                                        │
│   cove/forgejo/*    12  ● accessible                            │
│   cove/vault/*       3  ● accessible                            │
│   cove/runner/*      2  ● accessible                            │
│                                                                  │
│  [u] unseal  [r] rekey  [t] test token  [o] browser             │
│  [esc] back  [ctrl+p] commands  [?] help  [q] quit              │
└──────────────────────────────────────────────────────────────────┘
```

**Command palette: overlay on any mode (Journey 4, 5)**

```
┌─ Cove · overview ───────────────────────────────────────────────┐
│ ● UP (42h)                                                       │
│  forgejo ●  nginx ●  vault ●  dnsmasq ●                         │
│                                                                  │
│  ██████████████████████████████████████████████████████████████ │
│  █  > log                                                        █ │
│  █    tail forgejo logs                                          █ │
│  █    tail nginx logs                                            █ │
│  █    tail vault logs                                            █ │
│  █    tail dnsmasq logs                                          █ │
│  ██████████████████████████████████████████████████████████████ │
│                                                                  │
│  [esc] close palette  [enter] execute  [q] quit                  │
└─────────────────────────────────────────────────────────────────┘
```

### Why This Combination

| Journey | Served By | How |
|---------|-----------|-----|
| 1. Quick check | Overview mode | Land here. All services visible. Alerts prominent. < 2 seconds. |
| 2. Diagnose | Service detail mode | Enter on broken service → logs, resources, restart. |
| 3. Browse concerns | Concern modes | `v` for vault, `c` for certs, `n` for network, `d` for data. |
| 4. Execute task | Command palette | `ctrl+p`, type "renew certs", enter. No memorization. |
| 5. Explore | `?` help + palette | Help shows all modes and keys. Palette shows all commands. |

### Design Principles

1. **Overview first** — Landing shows the answer to "is it up?" immediately
2. **Alerts prominent** — Warnings (cert expiry, disk, seal) visible on overview
3. **Consistent chrome** — Every mode has: title bar (mode name), body (content), footer (keybindings)
4. **Esc always goes back** — From any detail mode, Esc returns to overview
5. **Command palette as universal fallback** — If you don't know the key, `ctrl+p` and type
6. **Live-updating** — Overview and detail modes poll every 3-5 seconds
7. **Keyboard-first, mouse-friendly** — All actions have keys; Textual supports mouse clicks

## What the TUI Is

A **Cove command center** — platform-specific, not a general Docker manager. Mode-based with command palette. Overview for status, detail modes for inspection, palette for task execution.

## What It Is Not

- Not a general Docker manager (no image list, volume management, network CRUD)
- Not a replacement for Lazydocker (which is a general Docker TUI)
- Not blocking scriptability (all subcommands remain)

## Honest Evaluation

### Arguments For

1. **Unified entry point** — `cove` is the Cove command. Running it bare should show you the state of your harbor.

2. **Cove-specific views** — Generic Docker TUIs don't know about Vault seal state, cert expiry, or DNS health.

3. **Discoverability** — Command palette means no memorization. `?` shows everything.

4. **No external dependency** — Users don't need Lazydocker for basic management. Lazydocker becomes optional.

5. **Consistent with platform identity** — "One command gives you a working platform."

### Arguments Against

1. **Dependency cost** — Textual adds ~3MB. Cove CLI is ~200KB. But Cove already requires Docker, Python, uv — 3MB is noise.

2. **Maintenance burden** — A good TUI is real work. But Textual handles most of the hard parts (layout, keybindings, mouse, theming).

3. **User preference** — Some users already have a preferred Docker TUI. Cove's TUI is complementary, not competing.

4. **Scope creep risk** — Mitigated by design: Cove-specific modes, not a Docker manager.

### Arguments That Are Weak

- **"Not scriptable"** — All subcommands remain. `cove status` for scripts. `watch cove status` works.
- **"Startup latency"** — Textual ~200ms. For a manually typed command, irrelevant.
- **"Accessibility"** — Terminal emulators handle TUIs. Subcommands for programmatic use.
- **"Breaks `watch cove`"** — `watch cove status` is correct.

## Relationship to Lazydocker

Lazydocker: general Docker TUI (all containers, images, volumes, networks, builds).

Cove TUI: Cove command center (4-5 services, Vault seal, cert expiry, DNS, data usage).

Complementary. User might:
- `cove` → check platform health, unseal Vault, renew certs
- `lazydocker` → inspect resource usage, prune images, manage non-Cove containers

## Decision

**TUI as default for bare `cove`.** Mode-based (overview + detail modes) with command palette. All subcommands remain for scripting. Textual implementation.

## Related Musings

- `docker-desktop-alternatives-for-cove-pod.md` — Colima migration context
- `cove-health-daemon.md` — Automated recovery; TUI shows health daemon status
- `gui-tools-for-cove.md` — Lazydocker as general Docker TUI; Cove TUI is platform-specific complement