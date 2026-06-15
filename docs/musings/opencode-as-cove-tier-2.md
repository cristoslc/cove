---
title: "AI Coding Harnesses as Cove Services"
created: 2026-06-13
revised: 2026-06-15
authored-by: cristos
status: Draft
---

# AI Coding Harnesses as Cove Services

## Why This Musing Exists

AI coding harnesses (OpenCode, Claude Code, Aider, etc.) all want filesystem access. The deployment question for Cove is: where does each harness run, how does the phone reach it, and does it need a tier-2 copy?

The key insight from research: **most harnesses don't have a native server mode**, so "drop-in" means containerize + bind mount. Only OpenCode has a server-first architecture. For everything else, the deployment pattern is the same: container with bind mounts, a web/remote surface (built-in or third-party), and nginx/Caddy in front.

This musing catalogs the harnesses I've considered for Cove, their tier-1/tier-2 viability, and recommends a deployment model. A detailed evidence-backed comparison is in the [`harness-catalog` trove](../troves/harness-catalog/synthesis.md).

## Roadmap

- **MVP** = the first thing shipped. One harness (OpenCode), tier 1 only. Proven end-to-end.
- **v1** = full tier-1 coverage. Multiple harnesses, all on the user workstation.
- **v2** = tier 2. Always-online box deployments, git-sync filesystem access, session replication.

## MVP Definition

**MVP is OpenCode only, on tier 1 only.**

- **Harness:** OpenCode. Native server mode, fits Cove's compose model without modification.
- **Tier:** 1 (user workstation). No tier-2 deployment in MVP. Tier-2 is v2.
- **Container runtime:** Docker via Colima. Cove's existing default.
- **Bind mounts:**
  - **Code (rw):** `~/Documents/code` — source repos the agent reads/writes
  - **Projects (rw):** `~/Documents/projects` — working directories outside the code repos
  - **OpenCode data (rw):** persistent location for SQLite sessions, e.g. `~/Documents/cove/opencode` — must survive container restarts
  - **Config (ro):** `~/.config/opencode` — opencode.jsonc, MCP server definitions, AGENTS.md
  - **Agent skills (ro):** `~/.agents` — skills, memories, AGENTS.md detail files (hot-reloaded at runtime)
  - **Claude skills (ro):** `~/.claude` — shared skill definitions (for future cross-harness use)

```yaml
# MVP compose service for OpenCode on tier 1
services:
  opencode:
    image: ghcr.io/anomalyco/opencode:latest
    container_name: cove-opencode
    ports:
      - "127.0.0.1:4096:4096"
    volumes:
      # Code (rw) — what the agent reads/writes
      - ~/Documents/code:/home/code:rw
      - ~/Documents/projects:/home/projects:rw
      # OpenCode data (rw) — SQLite sessions, must persist
      - ~/Documents/cove/opencode:/home/opencode/.local/share/opencode:rw
      # Config (ro) — opencode.jsonc, MCP defs
      - ~/.config/opencode:/home/opencode/.config/opencode:ro
      # Agent skills (ro) — skills, memories, AGENTS.md detail
      - ~/.agents:/home/opencode/.agents:ro
      # Claude skills (ro) — for future cross-harness skill sharing
      - ~/.claude:/home/opencode/.claude:ro
    environment:
      - OPENCODE_SERVER_PASSWORD=${OPENCODE_SERVER_PASSWORD}
      - OPENCODE_SERVER_HOSTNAME=0.0.0.0
      - OPENCODE_SERVER_PORT=4096
    restart: unless-stopped
```

Behind nginx at `opencode.cove` with HTTPS, accessible from phone via Tailscale.

**What MVP explicitly is not:**
- No tier-2 deployment. OpenCode on the always-online box is v2.
- No Claude Code, Aider, Codex CLI, Gemini CLI, or OpenClaw. Other harnesses are v1+.
- No kernel isolation (Lima VM). Container isolation via Colima is sufficient for MVP.
- No MCP server allowlist mechanism beyond what OpenCode provides natively.

**Why OpenCode only for MVP:**
- It's the only harness with a native server mode — fits Cove's compose model without modification
- The operator already uses it (this musing's origin)
- Sessions are portable across machines via the data mount
- One harness means one bind-mount contract, one nginx route, one auth flow — ship a small thing first

**v1 will add (still tier 1 only):**
- Claude Code (Remote Control, no local server needed)
- Aider, Codex CLI, Gemini CLI (ttyd-wrapped, same bind-mount contract)
- CloudCLI as a multi-harness dashboard
- Parameterized compose template so operators can pick which harnesses to run

**v2 will add (tier 2):**
- Tier-2 deployment of OpenCode (git-sync filesystem access, session replication)
- Tier-2 deployments of the v1 harnesses where they make sense
- swain-box-style Lima VM as a reference for operators who want kernel isolation

## Catalog of Harnesses

### Pattern A: Server-First (OpenCode) — MVP

OpenCode's TUI is a client to a local HTTP server. The server is the primary surface; the TUI is one of many possible clients. Designed for containerization — `ghcr.io/anomalyco/opencode` is the official image. Sessions in SQLite.

This is the v1 pattern. It's also the only one where tier-2 is genuinely useful (the server can run anywhere, session state is a known mount).

### Pattern B: CLI with Filesystem Dependency (Claude Code, Aider, Codex CLI, Gemini CLI) — v1

The harness needs direct filesystem access to work. Containerize it; bind-mount `~/Documents/code` and `~/Documents/projects`. The CLI is the entry point; web/remote access is bolted on through one of:

- **Built-in remote control** (Claude Code v2.1.51+, Feb 2026)
- **Third-party web shell** (ttyd wrapping the CLI in tmux)
- **Third-party session UI** (CloudCLI / siteboon/claudecodeui for full session management across Claude Code, OpenCode, Cursor CLI, Codex, Gemini-CLI)

For tier-2, these harnesses are mostly stateless — each invocation reads the working tree, does work, writes commits. Filesystem access on tier-2 is the hard problem (git sync or proxied I/O).

### Pattern C: IDE-Extension (Cline, Continue, Cursor) — out of scope

Run inside an editor. No standalone server. Not a drop-in for Cove. Skip for tier-2.

### Pattern D: Local-First Agent Platform (OpenClaw) — out of scope

Not a coding harness. A multi-channel personal-assistant platform (250K+ GitHub stars, formerly Clawdbot/Moltbot) with its own gateway, session model, and node pairing. WhatsApp/Telegram/Slack/Discord/iMessage/Signal as UI. Created by Peter Steinberger (who joined OpenAI in Feb 2026).

Could be considered for tier-2 deployment if the operator wants 24/7 agent availability via messaging apps. But it competes with the forge/git-bug stack for the operator's attention and workflow. Different product, different problem.

## Claude Code Remote Control — Changes the Story

Claude Code shipped **Remote Control** in February 2026 (v2.1.51+). It's a built-in feature that bridges a local Claude Code CLI session to `claude.ai/code` (web), the Claude iOS app, and the Claude Android app.

Key facts from the official docs:

- **Files stay local.** Remote Control is a window into a local session, not a cloud migration. MCP servers, tools, project config, and environment all stay on the operator's machine.
- **Outbound only.** No inbound ports. The local process registers with the Anthropic API and polls for work. Traffic flows over TLS with short-lived credentials.
- **Auth requirement.** Requires a Claude Max/Pro/Team/Enterprise subscription. API keys are not supported. Must be signed in via claude.ai.
- **Three modes.** `claude remote-control` (server mode, multiple sessions), `claude --remote-control` (interactive with remote access), `/remote-control` (mid-session activation).
- **Mobile push.** As of v2.1.110+, Claude can push to the mobile app on long task completion or when it needs input.
- **Limitations.** One remote session per interactive process. Local process must keep running. Extended network outage (>10 min) ends the session.

**Implication for Cove:** Claude Code doesn't need a tier-2 deployment. The session lives on the laptop, the phone connects via claude.ai/code, files never leave the machine. A Cove tier-1 container running `claude --remote-control` is sufficient.

## Third-Party Web Surfaces

For harnesses without built-in remote control, the web surface comes from elsewhere.

### ttyd (tsl0922)

C binary, 18K+ stars. Default port 7681. Wraps any command in a web-based terminal served via WebSocket. Basic auth, SSL support, Docker image. The canonical web-shell bridge.

```
ttyd -p 4097 -c user:pass claude
```

This puts Claude Code in a browser-accessible terminal. Loss: no session management, no diff view, no chat-style UX. Gain: works with any CLI, no harness modifications.

### CloudCLI (siteboon/claudecodeui)

A web/GUI for Claude Code, OpenCode, Cursor CLI, Codex, and Gemini-CLI. "Use it locally or remotely to view your active projects and sessions from everywhere." Sandboxed agents with hypervisor-level isolation. PM2 setup, remote server config.

More harness-aware than ttyd — knows about sessions, projects, and the differences between harnesses. A real multi-harness dashboard.

## swain-box — The Reference Pattern

[`~/code/swain-box/`](https://git.cove/~/code/swain-box) is a real, working deployment of **kernel-isolated harness deployment** using OpenCode:

- Lima VM (Apple VZ on macOS, QEMU on Linux) provides kernel isolation
- Caddy inside the VM on `:4097` reverse-proxies to `opencode serve` on `127.0.0.1:8848`
- Mounts: `~/.agents`, `~/.claude`, `~/.config/opencode` (ro); `~/Documents/code`, `~/Documents/projects`, `~/lima-opencode-data` (rw)
- VM is sole writer to `~/lima-opencode-data`; host reads for ccusage — no concurrent-write corruption
- 4 CPU / 4GiB RAM (reduced from 8GiB after measurement: opencode 1.31 GiB RSS, Caddy 34 MiB, Ubuntu idle ~300MB)

**The pattern is portable across harnesses.** Replace `opencode serve` with `claude --remote-control`, `aider`, or any CLI. The Caddyfile, mount topology, and lifecycle are harness-agnostic.

**Verdict:** Reference pattern, not service. Cove provides Docker containers via Colima as the default tier-1 deployment. swain-box's Lima VM pattern is documented as a reference for operators who want to replicate it outside of Cove. Cove does not bundle Lima VM orchestration into `cove up`.

**Full evidence:** [`swain-box/`](../troves/harness-catalog/sources/swain-box/) in the harness-catalog trove.

## Tier Placement Matrix

| Harness | Version | Tier 1 | Tier 2 | Web Surface |
|---------|:---:|:---:|:---:|-------------|
| **OpenCode** | **MVP** | ✅ Native server | ⏳ v2: git-sync | Native web UI |
| **Claude Code** | v1 | ✅ Container + bind mount | ⏳ v2: not needed (files stay on laptop) | `claude.ai/code` via Remote Control |
| **Aider** | v1 | ✅ Container + bind mount | ⏳ v2: git-sync (auto-commits) | ttyd or CloudCLI |
| **Codex CLI** | v1 | ✅ Container + bind mount | ⏳ v2: same as Aider | ttyd or CloudCLI |
| **Gemini CLI** | v1 | ✅ Container + bind mount | ⏳ v2: same as Aider | ttyd or CloudCLI |
| **CloudCLI** | v1 | ✅ Container | ⏳ v2: same | Native web UI (multi-harness) |
| **Cline** | — | ❌ IDE-only | ❌ | Editor |
| **Continue** | — | ❌ IDE-only, unmaintained | ❌ | Editor |
| **Cursor** | — | ❌ IDE-only | ❌ | Editor |
| **OpenHands** | — | ❌ | ⏳ v2: sandbox agent platform | Web |
| **OpenClaw** | — | ⚠️ Local install | ⏳ v2: self-host gateway | Messaging apps |

## Deployment Recommendations

### MVP: OpenCode on Tier 1

See the [MVP Definition](#mvp-definition) section above for the compose service. Single harness, single tier, Docker via Colima.

### v1: Multiple Harnesses on Tier 1

**Tier 1 — Claude Code:**

```yaml
services:
  claude-code:
    image: node:22-slim
    working_dir: /home/code
    command: claude --remote-control
    volumes:
      - ~/.claude:/home/node/.claude:ro
      - ~/Documents/code:/home/code:rw
    # No port mapping — uses outbound bridge to claude.ai/code
```

Phone access via claude.ai/code (web) or Claude mobile app. No port forwarding needed.

**Tier 1 — Aider, Codex CLI, Gemini CLI:**

```yaml
services:
  aider:
    image: python:3.12-slim
    command: ttyd -p 4097 -c ${AIDER_USER}:${AIDER_PASS} aider --model sonnet
    volumes:
      - ~/Documents/code:/home/code:rw
    ports: ["127.0.0.1:4097:4097"]
```

Phone access via `https://aider.cove` (nginx in front of ttyd).

**Tier 1 — CloudCLI (multi-harness dashboard):**

A web UI that spans Claude Code, OpenCode, Cursor CLI, Codex, Gemini-CLI. Operators who want one dashboard for all harnesses add this in v1.

### v2: Tier 2 (always-online box)

- **OpenCode**: same container as v1, git-sync filesystem access. Compose with periodic `git pull` for filesystem changes. Session data on a known mount. Session replication via SQLite export/import or CRDT is an open question.
- **Claude Code**: not necessary on tier-2. Remote Control bridges to the local CLI session. Tier-2 doesn't add value — the session must run on a machine with filesystem access.
- **Aider, Codex CLI, Gemini CLI**: stateless, can run on tier-2 with git-sync. Output is commits. Limited value — just runs in CI.
- **OpenClaw**: could be self-hosted on tier-2 for 24/7 availability via messaging apps. Different use case than coding.

## Open Questions

MVP questions (must resolve before MVP ships):
1. **Exact XDG path inside the container?** The compose mounts `~/Documents/cove/opencode` to `/home/opencode/.local/share/opencode` — verify this matches where the OpenCode server actually writes. May need to check the official image's `USER` and `HOME` directives.
2. **nginx auth — Tailscale or basic auth + TLS?** Tailscale gives zero-config auth for the phone surface. Basic auth + TLS is broader. MVP picks one.
3. **Restart behavior on laptop wake?** When the laptop sleeps and wakes, does the OpenCode container restart cleanly? Sessions persist in the bind mount, so this should work, but the SQLite WAL needs to be consistent.
4. **Resource limits?** LLM calls are expensive. MVP should set memory/CPU limits on the container.

v1 questions (resolve before adding more harnesses):
5. **Bind-mount conflicts?** Multiple harnesses (OpenCode, Claude Code, Aider) all want `~/Documents/code` rw. Do they interfere, or can they coexist with the same mount?
6. **CloudCLI integration with Cove's auth/nginx?** Does CloudCLI work behind Cove's nginx setup, or does it need its own routing?

v2 questions (defer):
7. **Tier-2 session replication?** OpenCode sessions are SQLite. How do you sync them between tier 1 and tier 2? Export/import? CRDT? Just accept that you can only have one active session per machine?
8. **OpenClaw integration?** Different product, different problem space. Not MVP, v1, or v2 unless the operator asks.

## Next Steps

MVP:
- Verify the OpenCode data path inside the container (`/home/opencode/.local/share/opencode`)
- Decide on auth model: Tailscale-only, or Tailscale + nginx basic auth
- Write the `cove up` integration — add the opencode service to Cove's compose stack
- Test: create a session, restart the container, verify session persists
- Test: access from phone via Tailscale, verify web UI works
- Document the MVP deployment in the Cove install docs

v1:
- Add Claude Code (Remote Control) — same bind-mount contract, different web surface
- Add parameterized compose template for CLI harness pattern (Aider/Codex/Gemini with ttyd)
- Evaluate CloudCLI as a multi-harness dashboard
- Test multi-harness coexistence on the same laptop

v2:
- Tier-2 OpenCode deployment (git-sync, session replication)
- swain-box Lima VM as a reference for operators who want kernel isolation

## Sources

Full evidence trail in [`docs/troves/harness-catalog/sources/`](../troves/harness-catalog/sources/):

- `claude-code-remote-control/` — code.claude.com official docs, snapshotted
- `claudecodeui/` — siteboon/claudecodeui GitHub
- `ttyd/` — tsl0922/ttyd GitHub
- `openclaw/` — openclaw/openclaw GitHub
- `swain-box/` — 10 files from ~/code/swain-box/ (ARCHITECTURE, PURPOSE, AGENTS, TECH-STACK, DEVELOPER-WORKFLOWS, USER-EXPERIENCE, opencode-dev.yaml, Caddyfile, plus 2 musings)

Synthesis: [`docs/troves/harness-catalog/synthesis.md`](../troves/harness-catalog/synthesis.md)
