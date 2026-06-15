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