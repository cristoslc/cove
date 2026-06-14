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
| TUI (Lazydocker-style) | Interactive, scrollable logs, resource graphs | Extra dep (or bundled binary), not scriptable, overkill for "is it up?" |
| Interactive menu | Discoverable | Not scriptable, extra deps |
| `cove status` command | Explicit, scriptable | Extra keystroke for common case |

## Why Not a TUI as Default?

1. **Different use case** — A TUI is for *interactive management* (scrolling logs, restarting containers, inspecting resources). The default command answers a *read-only question*: "is my harbor running?"

2. **Scriptability** — A static dashboard works in scripts, CI, SSH sessions, and `watch cove`. A TUI breaks all of these.

3. **Dependency cost** — Bundling a TUI (Textual, Bubble Tea, or a Go binary like Lazydocker) adds significant weight. Cove's CLI is a single Python package; adding a TUI framework or vendoring a binary contradicts "self-contained, three prerequisites."

4. **Lazydocker already exists** — The [gui-tools-for-cove.md](../gui-tools-for-cove.md) musing recommends Lazydocker for interactive management. Running `lazydocker` explicitly is the right UX for that mode; the default command shouldn't compete.

5. **Startup latency** — A TUI framework adds 100-500ms startup. The default command should be instant (<50ms).

6. **Accessibility** — Static text output works with screen readers, `less`, `grep`, and terminal recording. TUIs often don't.

## Decision

**Status dashboard as default command.** It's the highest-value view for the "is my harbor running?" use case that dominates daily interaction. Users who want help can still run `cove --help`.

## Related Musings

- `docker-desktop-alternatives-for-cove-pod.md` — Colima migration context
- `cove-health-daemon.md` — Automated recovery; dashboard shows health daemon status
- `gui-tools-for-cove.md` — Lazydocker for interactive management; dashboard is the read-only complement