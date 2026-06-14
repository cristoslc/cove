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

## The Proposal: TUI as Default

`cove` (no args) launches a TUI. All subcommands (`cove up`, `cove down`, `cove status`, `cove restart`, `cove logs`, `cove shell`) remain as CLI commands for scripting. The TUI is only the default for bare `cove`.

### What the TUI Shows

A Cove-specific dashboard — not a general Docker manager. Four services with Cove-relevant health:

```
┌─ Cove ──────────────────────────────────────────────────────┐
│ Status: UP  (since 09:42)                                    │
│                                                               │
│  cove-forgejo  ● running  healthy   https://git.cove/         │
│  cove-nginx    ● running  healthy   *.cove                    │
│  cove-vault    ● running  healthy   unsealed                   │
│  cove-dnsmasq  ● running  healthy   DNS resolution            │
│                                                               │
│ [1] Logs    [2] Restart   [3] Shell   [4] Open in browser     │
│ [q] Quit                                                      │
└───────────────────────────────────────────────────────────────┘
```

Keybindings or arrow keys to navigate. Selecting a service shows its logs, resource usage, or action menu. This is a **Cove platform dashboard**, not a Docker UI.

### What It Is Not

- Not a general Docker manager (no image list, volume management, network inspection)
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

1. **Dependency cost** — Textual adds ~3MB. A vendored Go binary (Lazydocker or custom) adds ~5-10MB. Cove CLI is currently ~200KB. This is the strongest argument against. However, Cove already requires Docker, Python, and uv — 3MB is noise in that context.

2. **Maintenance burden** — A good TUI is real work: keybindings, scrollback, resize, mouse support, theming, edge cases. Lazydocker has 30k stars and years of polish. Cove would own this surface area.

3. **User preference** — Some users already have a preferred Docker TUI. Cove's TUI is Cove-specific (not a Docker manager), so they're complementary, but the user might find it annoying to learn another interface.

4. **Scope creep risk** — Once you have a TUI, users will ask for more: image management, volume browsing, network inspection. The line between "Cove dashboard" and "Docker UI" blurs.

### Arguments That Are Weak (Prior Model's Mistakes)

- **"Not scriptable"** — All subcommands remain. `cove status` works in scripts. `watch cove status` works fine. This was a bad-faith argument.

- **"Startup latency"** — Textual cold start ~200ms. Go binary ~50ms. For a command the user types manually, this is irrelevant. The prior model inflated this.

- **"Accessibility"** — Terminal emulators handle TUIs fine with screen readers. And subcommands remain for programmatic use. Not a real concern.

- **"Breaks `watch cove`"** — `watch cove status` is the correct invocation. Nobody runs `watch docker` and expects it to work. This was a strawman.

## Relationship to Lazydocker

Lazydocker is a **general Docker TUI** — it shows all containers, images, volumes, networks, builds. It's useful for any Docker user.

Cove's TUI is a **Cove platform dashboard** — it shows 4-5 named services with Cove-specific health info (Vault seal state, Forgejo provisioning, cert expiry, DNS resolution).

They serve different purposes and are complementary. A user might:
- Use `cove` to check platform health and restart a service
- Use `lazydocker` to inspect resource usage, prune images, or manage non-Cove containers

Lazydocker is not replaced. It's the recommended general Docker TUI if the user wants one. Cove's TUI is Cove-specific.

## Decision

**TUI as default for bare `cove`.** All subcommands remain for scripting. The TUI is Cove-specific (not a Docker manager), so it doesn't compete with Lazydocker — they serve different purposes.

Implementation options:
- **Textual** (Python, ~3MB) — stays in the Python ecosystem, no vendored binary
- **Delegate to Lazydocker** — `cove` (no args) runs `lazydocker --filter name=cove-*` if installed, falls back to static dashboard
- **Vendored Go binary** — fastest startup, but adds build complexity

Textual is the most natural fit: same language as the CLI, lazy-importable (no startup cost for subcommands), and the Cove team already knows Python.

## Related Musings

- `docker-desktop-alternatives-for-cove-pod.md` — Colima migration context
- `cove-health-daemon.md` — Automated recovery; TUI shows health daemon status
- `gui-tools-for-cove.md` — Lazydocker as general Docker TUI; Cove TUI is platform-specific complement