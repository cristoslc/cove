---
title: "cove Default Command UX"
created: 2026-06-13
authored-by: nemotron-3-ultra:cloud
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

## Desired UX: Status Dashboard

When the user runs `cove` with no subcommand, show a **status dashboard** — the single most useful view for a solo developer who wants to know "is my harbor running?"

### Example Output

```
╭────────────────────────────────────────────────────────────────╮
│ Cove — Local Developer Platform                                │
╰────────────────────────────────────────────────────────────────╯

Status: UP (since 2026-06-13 09:42)

Containers:
  ✓ cove-forgejo     running  (healthy)   git.cove
  ✓ cove-nginx       running  (healthy)   *.cove, reverse proxy
  ✓ cove-vault       running  (healthy)   vault.cove, unsealed
  ✓ cove-dnsmasq     running  (healthy)   *.cove DNS resolution

Endpoints:
  Forgejo:   https://git.cove/
  Vault:     https://vault.cove/
  Registry:  https://registry.cove/
  Pages:     https://pages.cove/
  CI Runner: https://runner.cove/

Quick Actions:
  cove down           Stop all containers
  cove logs forgejo   Tail forgejo logs
  cove shell vault    Open shell in vault container
  cove ps             Show container status (this view)

Next Steps:
  • Push a repo:    git push cove main
  • Open Forgejo:   open https://git.cove/
  • Check Vault:    cove creds vault-get secret/myapp
```

### When Cove is Down

```
╭────────────────────────────────────────────────────────────────╮
│ Cove — Local Developer Platform                                │
╰────────────────────────────────────────────────────────────────╯

Status: DOWN

Quick Actions:
  cove up             Start Cove (provisions Forgejo, bootstraps Vault)
  cove up --no-sudo   Start without /etc/hosts update (if already configured)
  cove install        Inject AGENTS.md guidance for this project
```

### When Not in a Cove Project Directory

```
╭────────────────────────────────────────────────────────────────╮
│ Cove — Local Developer Platform                                │
╰────────────────────────────────────────────────────────────────╯

Not in a Cove project directory.

Quick Actions:
  cove init           Initialize a new Cove project here
  cove install -g     Install global AGENTS.md guidance (~/.agents/)
```

## Design Principles

1. **Status first** — The primary question is "is it running?"
2. **Actionable** — Every line that isn't status should be a command the user can run
3. **Context-aware** — Show different views based on state (up/down/not-in-project)
4. **Concise** — Fit on a standard terminal (80x24) without scrolling
5. **Offline-first** — No network calls; everything from local Docker state

## Implementation Approach

Add a default command to the Click group:

```python
@app.command(hidden=True)
@click.pass_context
def _default(ctx):
    """Show status dashboard when invoked without subcommand."""
    if ctx.invoked_subcommand is None:
        show_status_dashboard()
        ctx.exit()
```

The `show_status_dashboard()` function would:
1. Find compose directory (reuse `_find_compose_dir`)
2. Run `docker compose ps --format json` to get container state
3. Check health endpoints if containers are running
4. Render appropriate view

## Alternatives Considered

| Approach | Pros | Cons |
|----------|------|------|
| Current (help text) | Standard CLI behavior | Not useful daily |
| Status dashboard (proposed) | High value, immediate, scriptable, no deps | Static, no interactivity |
| TUI as default (`cove` launches TUI; `cove up/down/status/restart` remain CLI) | Unified management, discoverable, no extra tool needed | Extra dep, not scriptable, startup latency, accessibility |
| Interactive menu | Discoverable | Not scriptable, extra deps |
| `cove status` command | Explicit, scriptable | Extra keystroke for common case |

## TUI as Default: Deeper Analysis

The proposal: `cove` (no args) launches a TUI for interactive management; `cove up`, `cove down`, `cove status`, `cove restart`, `cove logs`, `cove shell` remain CLI commands for scripting.

### Arguments For

- **Unified entry point** — One command (`cove`) does everything: status at a glance, then navigate to logs, restart, shell, resources
- **Discoverability** — New users explore features without reading docs; keybindings visible in UI
- **No external dependency on Lazydocker** — Cove owns the management UX; users don't need to install/configure a separate tool
- **Cove-specific views** — Can show Forgejo provisioning status, Vault seal state, cert expiry, DNS health — things generic Docker TUIs don't surface
- **Consistent with `cove up/down`** — Feels like a cohesive platform, not a CLI + separate TUI

### Arguments Against

- **Dependency cost** — Textual (~3MB + deps) or vendored Go binary (~5-10MB). Cove CLI is currently ~200KB. Contradicts "three prerequisites."
- **Scriptability broken for default case** — `watch cove`, `cove` in CI, `ssh host cove` all break. Workaround: `cove status` for scriptable output, but now two commands for "status."
- **Startup latency** — Textual cold start ~200-400ms; Go binary ~50-100ms. Dashboard is <50ms.
- **Accessibility** — TUIs are poor citizens for screen readers, terminal recording, `grep`, `less`.
- **Maintenance burden** — Building a good TUI is a project in itself (keybindings, scrollback, resize handling, mouse support, themeability). Lazydocker has 30k stars and years of polish.
- **User preference** — Some users already have a preferred Docker TUI (Lazydocker, Dozzle, ctop, Docker Desktop). Forcing Cove's TUI creates friction.
- **Scope creep** — Cove is a platform orchestrator, not a Docker UI. A TUI pulls toward becoming a general Docker manager.

### Hybrid Compromise

`cove` (no args) → **static dashboard** (fast, scriptable, accessible)
`cove tui` → **optional TUI** (lazy-loaded, only if user wants it, can vendor Lazydocker or build minimal Textual app)

This keeps the default fast and scriptable while offering interactive mode explicitly.

## Why Not Replace Lazydocker Entirely?

Even if Cove builds a TUI, Lazydocker remains the recommended fallback because:

1. **Maturity** — 30k+ stars, handles edge cases Cove's TUI won't (custom networks, buildx, compose profiles, plugin ecosystems)
2. **User choice** — "Cove manages the platform; you choose your Docker UI"
3. **Zero maintenance** — Cove doesn't own Docker UI bugs

## Decision

**Status dashboard as default command (`cove`).** Optional `cove tui` subcommand for interactive mode (lazy-loaded, can delegate to Lazydocker or build minimal Textual app). `cove up/down/status/restart/logs/shell` remain CLI for scripting.

This preserves scriptability, fast startup, and accessibility for the 90% case ("is it up?"), while offering a path to interactive management without forcing a heavy dependency on all users.

## Related Musings

- `docker-desktop-alternatives-for-cove-pod.md` — Colima migration context
- `cove-health-daemon.md` — Automated recovery; dashboard shows health daemon status
- `gui-tools-for-cove.md` — Lazydocker for interactive management; dashboard is the read-only complement