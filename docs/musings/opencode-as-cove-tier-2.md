# Opencode Server as Cove Service

Right now, I'm using opencode on my laptop with the server running on the laptop itself. This allows me to access it from my phone, but it's subject to the same tier-1/tier-2 access issues as Cove itself. The two main reasons I use opencode server are session continuity and remote access.

## Research Findings

### OpenCode Architecture

OpenCode is a TypeScript/Bun monorepo with a **local HTTP server architecture** — even the TUI starts a local HTTP server on `127.0.0.1` and acts as a client to it. Key architectural facts:

- **Server mode**: `opencode serve` exposes a full HTTP API (Hono + Effect-ts) with OpenAPI 3.1 spec
- **Web UI**: `opencode web` provides a browser-based interface (SolidJS)
- **Sessions**: Stored in SQLite (Drizzle ORM), supports create/fork/compact/abort/share/revert
- **File access**: Direct filesystem access via REST endpoints (`GET /file/content?path=...`)
- **Auth**: HTTP Basic Auth via `OPENCODE_SERVER_PASSWORD`
- **Docker**: Official image at `ghcr.io/anomalyco/opencode` (Alpine, multi-arch)
- **SDK**: `@opencode-ai/sdk` for programmatic access
- **Plugins**: Plugin system hooks into all events
- **MCP support**: Yes

### Cove's Two-Tier Model (from multi-stage-cove.md)

| Aspect | Tier 1 (Local) | Tier 2 (Always-Online) |
|--------|:---:|:---:|
| Location | Laptop | Raspberry Pi / always-on box |
| Offline-first | ✅ Immutable | ❌ Requires network |
| Forgejo | ❌ | ✅ |
| git-bug CLI | ✅ | ❌ |
| git-bug web UI | ❌ | ✅ |
| Phone access | ❌ | ✅ (HTTPS) |

### Alternative Harnesses

| Harness | Server Mode | Web UI | Docker | Notes |
|---------|:---:|:---:|:---:|-------|
| **OpenCode** | ✅ Native | ✅ | ✅ Official | Only one with server-first architecture |
| Aider | ❌ CLI only | ❌ | ❌ Community | Python, 46K stars |
| Continue | ❌ IDE ext | ❌ | ❌ | Read-only, no longer maintained |
| Claude Code | ❌ CLI only | ❌ | ❌ | Proprietary |

OpenCode is the **only** AI coding harness with a native server mode, web UI, and official Docker image. This makes it the clear choice for Cove integration.

## Tier-1: OpenCode Server on Local Machine (No-Brainer)

Running opencode server as a Tier-1 Cove service is straightforward:

```
┌─ Laptop (Tier 1) ──────────────────────┐
│  opencode serve --hostname 0.0.0.0     │
│  Binds to 127.0.0.1:4096              │
│  Access from phone via Tailscale       │
│  Sessions in local SQLite              │
│  Direct filesystem access to ~/code/   │
└────────────────────────────────────────┘
```

**Benefits:**
- Session continuity across laptop sleep/wake cycles
- Remote access from phone via Tailscale (already works)
- No new infrastructure needed
- Filesystem access is trivial (same machine)

**How to add to Cove:**
- Add a `compose/opencode/` service definition
- Mount `~/Documents/code/` or `~/code/` into the container
- Expose port 4096 behind nginx at `opencode.cove`
- Set `OPENCODE_SERVER_PASSWORD` from Vault
- Persist SQLite sessions in `~/Documents/cove/opencode/`

## Tier-2: OpenCode Server on Always-Online Box (Open Question)

The hard question: can opencode server run on Tier-2 and still be useful?

### The Filesystem Problem

OpenCode's core value is reading/writing files and running shell commands. A Tier-2 server doesn't have access to the laptop's filesystem. Solutions ranked by feasibility:

**Option A: Git-based sync (most aligned with Cove philosophy)**
```
Tier-2 opencode works on a git clone of the repo.
Agent edits files, commits, pushes.
Laptop pulls when online.
```
- Pro: Aligns with Cove's git-based sync model
- Pro: Works offline on laptop (just pull before disconnecting)
- Con: Agent can only work on repos that exist on Tier-2
- Con: No access to uncommitted changes on laptop
- Con: Can't run project-specific commands that need local env

**Option B: Tailscale/Funnel (simplest)**
```
Tier-1 opencode server is accessible via Tailscale Funnel.
Phone connects directly to laptop's opencode server.
No Tier-2 opencode needed.
```
- Pro: Zero new infrastructure
- Pro: Full filesystem access
- Con: Laptop must be online and awake
- Con: Defeats the purpose of Tier-2 (laptop independence)

**Option C: Hybrid — Tier-2 as proxy/relay**
```
Tier-2 runs opencode server with git clones.
Tier-1 runs opencode server with full filesystem access.
Phone connects to whichever is available.
Session state syncs between them (SQLite replication?).
```
- Pro: Best of both worlds
- Con: Session sync is complex (SQLite doesn't do multi-master)
- Con: Two servers, two sets of sessions

**Option D: Tier-2 as stateless compute + file proxy**
```
Tier-2 opencode server has no local filesystem.
File operations are proxied to Tier-1 via Tailscale.
Tier-2 handles LLM calls, session state, web UI.
Tier-1 handles file I/O and shell execution.
```
- Pro: Single session state on Tier-2
- Pro: Files stay on laptop
- Con: Requires custom proxy layer (not built into opencode)
- Con: Laptop must be online for file operations

### The Session Continuity Problem

Even with filesystem access solved, there's the session problem:

- Sessions are stored in local SQLite on whichever server you're using
- If you start a session on Tier-1 (laptop) and want to continue on Tier-2 (phone), the session history doesn't follow
- OpenCode has a `compact` feature (summarize session → create child session), but it's not designed for cross-server sync

### Recommendation

**For now: Tier-1 only.** Run opencode server on the local machine as a Cove service. This gives us:
- Session continuity (server stays up across terminal sessions)
- Remote access via Tailscale (phone can reach laptop's opencode server)
- Full filesystem access
- No architectural complexity

**Tier-2 opencode is not worth the complexity** until there's a clear use case that Tier-1 + Tailscale doesn't solve. The filesystem access problem is fundamental — an AI coding agent without filesystem access is severely limited.

### What Tier-1 as a Cove Service Looks Like

```yaml
# compose/opencode/compose.yaml
services:
  opencode:
    image: ghcr.io/anomalyco/opencode:latest
    container_name: cove-opencode
    ports:
      - "127.0.0.1:4096:4096"
    volumes:
      - ~/Documents/code:/home/code:ro  # read-only access to projects
      - ~/Documents/cove/opencode:/home/opencode  # session persistence
    environment:
      - OPENCODE_SERVER_PASSWORD=${OPENCODE_SERVER_PASSWORD}
      - OPENCODE_SERVER_HOSTNAME=0.0.0.0
      - OPENCODE_SERVER_PORT=4096
    restart: unless-stopped
```

Behind nginx at `opencode.cove` with HTTPS, accessible from phone via Tailscale.

### Open Questions

1. **Read-only vs read-write filesystem?** Read-only is safer but limits the agent. Read-write means the agent can modify files on the host.
2. **Which directories to mount?** `~/Documents/code/` covers Cove projects. What about other code locations?
3. **LLM API keys?** Stored in Vault, injected as env vars. The agent needs access to Anthropic/OpenAI APIs.
4. **Resource limits?** LLM calls are expensive. Need to prevent runaway token usage.
5. **Multiple projects?** OpenCode works on one project at a time. The web UI lets you switch, but sessions are per-project.

## Harness Evaluation: Cove Drop-In Candidates

Not all AI coding harnesses can serve as Cove services. A harness needs either a server/gateway architecture (for web UI access and API endpoints) or a containerizable CLI (for headless task execution). Here's a wider evaluation of candidates.

### Harness Architecture Categories

| Category | Server Component | Web UI | Containerizable | Cove Fit |
|----------|:---:|:---:|:---:|:---:|
| **Server-first** (HTTP API + web UI) | Native | Native | Official image | Tier-1 and Tier-2 |
| **Gateway-first** (agent runtime) | Gateway daemon | Built-in | Official image | Tier-2 compute |
| **CLI-only** (terminal tool) | None | None | Community images | Tier-1 only (via opencode) |

### OpenClaw

**Architecture:** Gateway-first. OpenClaw runs as a long-lived Node.js daemon (the "gateway") that routes messages from channels (Telegram, Slack, Discord, WhatsApp, web chat) to AI coding agents. It has a web UI, Docker support, and a plugin system (skills, harnesses). The Codex harness integrates OpenAI's Codex CLI for coding tasks.

**Cove potential:**

```
┌─ Tier 2 ───────────────────────────────┐
│  OpenClaw gateway (Node.js daemon)      │
│  Port 18789 (WebSocket)                │
│  Port 8443 (web UI)                     │
│  Codex harness for coding tasks         │
│  Docker sandbox for agent execution     │
│  Telegram/Slack/Discord channels        │
│  LLM API keys from Vault               │
└─────────────────────────────────────────┘
```

**What OpenClaw could do on Tier-2:**
- Be the always-on agent that the phone talks to via Telegram/WhatsApp
- Execute coding tasks on git clones on Tier-2 (Option A from the filesystem problem)
- Act as an intermediary: phone sends a message → OpenClaw gateway → Codex harness → edits files on Tier-2 git clone → commits → pushes → laptop pulls when online
- Provide web chat access at `agent.cove`

**What it can't do on Tier-2:**
- Access the laptop's filesystem (same filesystem problem as OpenCode)
- Run project-specific local commands (tests that need local env, Docker, etc.)
- Continue a laptop session (different gateway, different state)

**Split-tier potential:**

OpenClaw's architecture is more amenable to split-tier than OpenCode because the gateway is designed as a routing layer. The gateway could run on Tier-2 (always reachable) while delegating file operations to Tier-1 via Tailscale:

```
┌─ Tier 2 ──────────────────────┐     ┌─ Tier 1 ───────────────────┐
│  OpenClaw gateway              │────▶│  Laptop filesystem          │
│  (routing, LLM calls, web UI) │     │  (file I/O via Tailscale)   │
│  Docker sandbox                │     │  Shell execution            │
└────────────────────────────────┘     └────────────────────────────┘
```

This is Option D from the filesystem problem, but OpenClaw's plugin system makes it more feasible than with OpenCode — a custom skill could proxy file operations to Tier-1. However, this still requires the laptop to be online for file operations, which defeats Tier-2's purpose.

**Realistic Cove integration:**

- **Tier-1:** OpenClaw on the laptop as a Cove service, alongside OpenCode. OpenClaw handles messaging channels (Telegram, WhatsApp), OpenCode handles coding sessions. The phone reaches OpenClaw via Tailscale when the laptop is online.
- **Tier-2:** OpenClaw gateway on the always-on box. Limited to git-clone-based work (Option A). Useful for "start a task from your phone, review it on your laptop later" workflows. Not a replacement for Tier-1 OpenCode.

**Verdict:** OpenClaw is complementary to OpenCode, not a replacement. It adds channel integration (Telegram, WhatsApp) that OpenCode doesn't have. But for coding tasks, OpenCode's server-first architecture with direct filesystem access is more practical. OpenClaw on Tier-2 could handle "read the logs" or "create a git-bug issue" tasks that don't need the laptop's filesystem.

### Claude Code

**Architecture:** CLI only. No server mode, no web UI, no API. Runs as a terminal command (`claude`). Proprietary (Anthropic). Multiple community Docker images exist for containerization, but they're all wrappers around the CLI.

**Cove potential:**

Claude Code can't serve as a Cove service directly — it has no server component. But it can be invoked from within other harnesses:

- **From OpenCode:** OpenCode could invoke `claude` as a sub-agent for specific tasks (though OpenCode uses its own model routing)
- **From OpenClaw:** OpenClaw's Codex harness already integrates OpenAI's Codex; a similar harness could integrate Claude Code
- **From Cove CLI:** `cove code` could invoke `claude` as a backend, similar to how Aider can use different models

**Containerized on Tier-2:**

```yaml
# Conceptual — Claude Code as a Tier-2 container
services:
  claude-code:
    image: ghcr.io/Zeeno-atl/claude-code:latest
    volumes:
      - /opt/cove/project:/workspace
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
    # No server port — CLI only, invoked on demand
```

This is essentially Option A (git-clone-based work) with Claude Code instead of OpenCode. Same filesystem constraints apply — the agent can only work on files that exist in the container's mounted volumes.

**Verdict:** Claude Code is a model backend, not a service architecture. It can run inside other harnesses or as a containerized CLI on Tier-2, but it doesn't add Cove service capabilities by itself.

### Aider

**Architecture:** CLI only. Terminal-based pair programmer. Has an experimental browser UI (`aider --browser`). Docker images exist (official: `paulgauthier/aider`, `paulgauthier/aider-full`). Python-based.

**Cove potential:**

Aider's browser mode (`--browser`) provides a minimal web UI, but it's not designed for multi-user or persistent server use. It starts a local HTTP server for the browser interface, but there's no authentication, no session management, and no API — it's just a thin wrapper around the CLI.

AiderDesk (separate project) provides a richer GUI with project/task management, but it's a desktop app, not a server.

**Containerized on Tier-2:**

Same as Claude Code — Aider in a container with a mounted git clone, invoked on demand. No persistent server, no web UI suitable for phone access. Aider's strength is its git integration (auto-commits, repo map), which works well with Option A (git-clone-based work on Tier-2).

**Verdict:** Aider is a CLI tool, not a Cove service. It could be invoked from OpenCode or OpenClaw as a sub-agent, or run containerized for on-demand coding tasks on Tier-2. Not a drop-in Cove service.

### Continue

**Architecture:** IDE extension (VS Code, JetBrains). No server mode, no standalone web UI. Read-only in the context of Cove services (it can't be a Cove service). The project is no longer actively maintained.

**Verdict:** Not applicable. Continue is an IDE extension, not a service.

### Comparison Matrix for Cove Integration

| Harness | Tier-1 Service | Tier-2 Service | Phone Access | Split-Tier | Notes |
|--------|:---:|:---:|:---:|:---:|-------|
| **OpenCode** | ✅ Native | ⚠️ Limited | ✅ Web UI | ⚠️ Hard | Server-first, web UI, direct filesystem. Tier-2 limited by filesystem access. |
| **OpenClaw** | ✅ Native | ✅ Native | ✅ Channels + Web | ⚠️ Possible | Gateway-first, channel integration, Docker sandbox. Can route file ops to Tier-1 via Tailscale. |
| **Claude Code** | ❌ CLI only | ❌ CLI only | ❌ | ❌ | Proprietary CLI. Can be invoked from other harnesses. |
| **Aider** | ❌ CLI only | ❌ CLI only | ⚠️ Browser mode | ❌ | Python CLI. Auto-commits are good for git-clone workflows. |
| **Continue** | ❌ IDE only | ❌ | ❌ | ❌ | Unmaintained IDE extension. |

### Realistic Multi-Harness Cove Setup

Rather than picking one harness, Cove could offer multiple as compose services, each serving a different purpose:

```yaml
# compose/ai/compose.yaml — AI harnesses as Cove services
services:
  opencode:
    # Primary coding agent — Tier-1 only
    image: ghcr.io/anomalyco/opencode:latest
    ports: ["127.0.0.1:4096:4096"]
    volumes:
      - ~/Documents/code:/home/code
      - ~/Documents/cove/opencode:/home/opencode
    environment:
      - OPENCODE_SERVER_PASSWORD=${OPENCODE_SERVER_PASSWORD}

  openclaw:
    # Channel agent — Tier-1 or Tier-2
    image: openclaw/openclaw:latest
    ports: ["127.0.0.1:18789:18789", "127.0.0.1:8443:8443"]
    volumes:
      - ./openclaw/config:/home/openclaw/.openclaw
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - OPENAI_API_KEY=${OPENAI_API_KEY}
```

**On Tier-1 (laptop):**
- OpenCode at `opencode.cove` — primary coding interface, full filesystem access
- OpenClaw at `agent.cove` — messaging channels, always-on agent

**On Tier-2 (always-on box):**
- OpenClaw at `agent.cove` — messaging channels, git-clone-based coding tasks
- OpenCode at `opencode.cove` — read-only access to git clones, limited utility
- No Claude Code, Aider, or Continue — they need interactive terminals

**On phone:**
- `agent.cove` → OpenClaw web chat for quick questions and task dispatching
- `opencode.cove` → OpenCode web UI for coding sessions (when laptop is online)
- Both via Tailscale (Tier-1) or direct HTTPS (Tier-2)

### Why OpenCode Remains the Primary Harness

OpenCode's server-first architecture makes it the only harness that works as a Cove service for interactive coding. The other harnesses add capabilities (channels, sub-agents, model routing) but don't replace OpenCode's core value: a persistent, web-accessible coding session with direct filesystem access.

OpenClaw adds channel integration (Telegram, WhatsApp, Discord) that OpenCode doesn't have. On Tier-2, OpenClaw can handle "quick tasks from the phone" — reading logs, checking git status, creating issues — without needing the laptop's filesystem. For actual coding work, the operator connects to OpenCode on Tier-1.

The multi-harness approach gives Cove the best of both worlds: OpenCode for coding, OpenClaw for always-on channel-based interaction, and Claude Code/Aider as on-demand sub-agents invoked by either.