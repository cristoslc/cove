# Harness Catalog for Cove Integration — Trove Synthesis

## Key Findings

AI coding harnesses have a rich ecosystem of web/desktop UIs and orchestration layers. Cove needs to pick which to integrate, which to leave as operator choice, and which to skip. This synthesis covers the major options found as of June 2026, plus the OpenCode data/backend story.

## OpenCode Web/Desktop UI Landscape (Comprehensively Crawled)

The musing's previous version named only `ttyd`, `CloudCLI`, and Claude Code Remote Control as web surfaces. There are many more:

### OpenCode-Native UIs

| Project | Author | Stars | Type | Notes |
|---------|--------|:---:|------|-------|
| **OpenCode web** (`opencode web`) | anomalyco (official) | n/a | Built-in | Alpha, mDNS for multiple instances, OPENCODE_SERVER_USERNAME/PASSWORD for basic auth. **Auth has known bugs** — see issues. |
| **CodeNomad** (`npx @neuralnomads/codenomad`) | NeuralNomadsAI | 1.9k | Desktop + Server | "AI Coding Cockpit for OpenCode." Multi-instance workspace, remote access, session management, voice input, git worktrees, sidecars (VSCode, ttyd). SolidJS + Electron/Tauri. MIT. |
| **Palot** | ItsWendell | — | Desktop (Electron) | Multi-agent GUI for OpenCode. Migrates from Claude Code/Cursor — converts global settings, MCP servers, agents, commands, rules (CLAUDE.md → AGENTS.md), hooks. |
| **opencode-gui** | jazarie2 | — | Web | Multi-instance, multi-folder parallel execution. |
| **pk-opencode-webui** | prokube | — | Web | Prefix-aware (reverse-proxy friendly). Multi-project workspace, MCP management, Telegram bridge. |
| **opencode-manager** | chriswritescode-dev | — | Web (PWA) | Mobile-first. Push notifications, Bun+Hono, `ocm` CLI to attach local TUI to hosted server. Tarball sync of working tree. |

### Generic Multi-CLI Dashboards

| Project | Author | Stars | Supports | Notes |
|---------|--------|:---:|----------|-------|
| **CloudCLI / claudecodeui** | siteboon | — | Claude Code, OpenCode, Cursor CLI, Codex, Gemini | Web/GUI. Plugin system, sandboxed agents (sbx CLI). Extends Claude Code natively. |
| **AionUi** | — | — | Claude Code, Cursor CLI, Codex, Gemini | "Multi-CLI Swiss Army knife." |
| **ttyd** | tsl0922 | 18k+ | Any CLI | Web-shell bridge. Default port 7681. Not harness-aware. |

### Claude Code-Specific UIs

| Project | Author | Notes |
|---------|--------|-------|
| **Claude Code Remote Control** | Anthropic (built-in) | v2.1.51+, Feb 2026. Bridge to claude.ai/code + mobile apps. Outbound only. Subscription required. |
| **Nimbalyst** | — | Desktop GUI. Multi-session, visual editing. |
| **Claudia GUI** | — | Visual project management. |
| **opcode** | winfunc | Tauri 2. Custom agents, usage tracking. |
| **Claudeck** | Hamed Farag | Browser UI via Claude Code SDK. |
| **claude-dashboard** | — | k9s-inspired TUI for tmux sessions. |
| **Claudraband** | — | Wraps Claude Code TUI in controlled terminal. |
| **Happy Coder** | — | Mobile companion, encrypted. |

## OpenCode Storage and Paths

Confirmed from issue #6669 and XDG spec:

- **Config:** `~/.config/opencode` (or `$XDG_CONFIG_HOME/opencode` if set, or `~/Library/Application Support/opencode` on macOS)
- **Data:** `~/.local/share/opencode` (or `$XDG_DATA_HOME/opencode` if set)
- **Cache:** `~/.cache/opencode`
- **Old/deprecated:** `~/.opencode/` was the original install path; the install script used `~/.opencode/bin` while runtime used XDG paths. There's an open issue to align these.

The musing's claim that data lives in `~/.local/share/opencode` is correct (XDG default). Config in `~/.config/opencode` is correct.

The user noted two open questions:
- Does OpenCode actually load agent skills from `~/.agents/`? — **OpenCode's config system** uses `~/.config/opencode/` for its own config (opencode.jsonc, MCP defs, AGENTS.md, custom commands, etc.). The `~/.agents/` directory is a swain-box convention (a symlinked directory the operator maintains for cross-tool skills). It is NOT an OpenCode-native path — OpenCode doesn't know about it. swain-box mounts it so MCP filesystem tools can serve those files. **For OpenCode directly, AGENTS.md and skills live in `~/.config/opencode/`.**
- Hot-reload of `~/.agents/` — N/A; OpenCode doesn't load from there. It hot-reloads its own config from `~/.config/opencode/`. Whether that hot-reload works for ALL config types (custom commands, plugins) is a separate question — the swain-box musing notes that "config should be hot-reloadable (no restart needed)" but this is an aspirational claim, not a verified fact.

**Musing claim that needs correction:** "Agent skills (ro): `~/.agents/` — hot-reloaded at runtime" — should be "OpenCode config (ro): `~/.config/opencode/` — opencode.jsonc, MCP defs, AGENTS.md. Hot-reload is intended but not fully verified."

## OpenCode Non-SQLite Backends (F2)

**Verdict: No native support, no roadmap for it.**

- **Issue #7840** (`sqlite vs embedded postgres`) was **closed** without implementation. Reasoning: SQLite is sufficient for single-user local use; Postgres would add complexity without solving a real problem for MVP/v1.
- **opencode-database-plugin** (aemr3) is a third-party plugin that *logs* sessions/messages/tool executions/token usage to Postgres, but it does NOT replace the session store. OpenCode still uses SQLite for active session state. The plugin is a read-only mirror.
- **OpenClaw has the same situation** — issue #1568 requests Postgres+pgvector backend, open since Feb 2026, not implemented.

**Implication for v2 session replication:**
- Can't do multi-master replication at the database layer (no CRDT, no Postgres backend)
- v2 options: (a) accept single-machine sessions, manual export/import; (b) live-migrate during sync windows (pause session, copy SQLite, resume on tier-2); (c) build a sync layer on top of SQLite (e.g., last-writer-wins on individual fields, treat it as an event log)
- The closed issue + the plugin approach suggests v2 session sync is hard and may not be worth it — better to keep tier-2 as a fresh instance that imports from tier-1 on demand, or accept that operator uses one machine at a time

## OpenCode Web UI Auth Bugs (F7)

Multiple open issues confirm the auth bug:

- **#9066** — "Failing to authenticate into web UI when username or password is set" — auth dialog keeps re-appearing
- **#18325** — "opencode-web Basic Auth Bug" — refreshing the page results in repetitive prompts
- **#17376** — "Infinite Authentication Loop when opening Terminal in v1.2.25"
- **#8676** — Plugin client returns 401 when password is set (Desktop only)
- **#9706** — Plugin client missing Authorization header

**Status:** All open, none closed. The basic auth implementation has been buggy for several releases.

**Cove's existing reverse proxy:** nginx (`compose/nginx/default.conf.j2`), not Caddy. The pattern is `proxy_pass` with `proxy_set_header` for X-Real-IP, X-Forwarded-For, X-Forwarded-Proto. Sites are: `git.cove` (Forgejo), `vault.cove` (Vault), `hc.cove` (health check), catch-all to Forgejo.

**Recommendation:** Add an `opencode.cove` block to the nginx template, following the same pattern. Proxy `127.0.0.1:4096` (the OpenCode container). This:
1. Solves the auth problem for the MVP (TLS termination at nginx, OpenCode auth still works because nginx passes through)
2. Provides a consistent URL pattern (`*.cove`)
3. Sets up the pattern for future harnesses (Claude Code Remote Control uses outbound, but ttyd-wrapped harnesses would also need a `*.cove` block)

The Tailscale question is separate: Tailscale gives zero-config auth for the phone surface, but only if the phone is on the Tailscale network. For phone browsers on cellular, you need actual TLS auth (basic auth, or session cookies from a login flow).

## Sources

### Web sources (snapshotted)

**OpenCode UIs:**
- `codenomad/` — github.com/NeuralNomadsAI/CodeNomad, 1.9k stars, MIT
- `palot/` — github.com/ItsWendell/palot
- `pk-opencode-webui/` — github.com/prokube/pk-opencode-webui
- `opencode-manager/` — github.com/chriswritescode-dev/opencode-manager
- `opencode-web-docs/` — opencode.ai/docs/web (official docs)

**Claude Code UIs:**
- `claudecodeui/` — github.com/siteboon/claudecodeui (CloudCLI)
- `opcode/` — github.com/winfunc/opcode
- (TUI/Codestral/web-explorer alternatives mentioned in `claudecodeui/` README)

**Generic:**
- `ttyd/` — github.com/tsl0922/ttyd, 18k+ stars

**OpenCode issues (referenced):**
- `claude-code-remote-control/` — code.claude.com official docs
- `opencode-sqlite-vs-postgres/` — issue #7840 (closed, no native Postgres)
- `opencode-auth-bug-18325/` — issue #18325 (basic auth bug, open)
- `opencode-auth-loop-17376/` — issue #17376 (infinite auth loop, open)

**Personal-assistant:**
- `openclaw/` — github.com/openclaw/openclaw, 250k+ stars

### Local sources (operator's host — working reference)

- `oc-zsh-functions/functions.opencode.zsh` — zsh functions sourced from `~/.zshrc`. Provides `oc-tui`, `oc-web`, `oc-restart`, `oc-stop`, `oc-vacuum`, `oc-memwatch`, `oc-direct`. The actual working Caddy + opencode setup, including the auth-bypass trick, watchdog, and session-repair flow.
- `oc-zsh-functions/Caddyfile` — the working Caddy config with `header_up Authorization` bypass for the OpenCode auth bug.

### Local sources (swain-box files)

- `swain-box/ARCHITECTURE.md` — system context, containers, mount topology
- `swain-box/PURPOSE.md` — single-line purpose
- `swain-box/AGENTS.md` — agent workflow notes
- `swain-box/TECH-STACK.md` — host, guest OS, toolchain
- `swain-box/DEVELOPER-WORKFLOWS.md` — VM lifecycle, data management
- `swain-box/USER-EXPERIENCE.md` — install, quality attributes
- `swain-box/opencode-dev.yaml` — Lima VM config
- `swain-box/Caddyfile` — reverse proxy config (Lima, not Cove)
- `swain-box/docs/musings/vm-disk-access-topology.md` — mount plan
- `swain-box/docs/musings/lighter-alternatives-to-8gb-vm.md` — VM sizing notes

## Gaps

- CodeNomad/Palot/opencode-gui UX not hands-on tested — relying on README claims
- OpenCode hot-reload of `~/.config/opencode/` not verified empirically
- OpenClaw tier-2 use cases (recurring workflows, PR monitoring) not deeply explored
- Claude Code ACP layer (Agent Client Protocol) — not researched. Would let Claude Code be wrapped server-side, enabling tier-2. Worth a follow-up musing.
- Restart-on-laptop-wake spike not performed
- Cove nginx pattern is in `default.conf.j2` but adding new sites requires Ansible templating — not validated
- Non-SQLite session replication approach (CRDT, event log) not designed
