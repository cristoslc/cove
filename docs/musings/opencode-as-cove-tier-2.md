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

## Harness Catalog

This section evaluates AI coding harnesses as Cove drop-ins. The key question for each is: **can it run on Tier 1 and/or Tier 2, and is the split-tier architecture viable?**

### Evaluation Criteria

A harness's tier-placement viability depends on three things:

1. **Filesystem access model** — does it need direct host access, or can it operate on a bind-mounted directory?
2. **Server architecture** — does it have a native server mode (HTTP), or is it CLI-only with sessions stored locally?
3. **Web UI** — is there a browser-based interface, or must the operator use a terminal client?

These three determine whether a harness can:
- Run in a container with a bind mount (most can)
- Be accessed from a phone over HTTPS (needs server + web UI)
- Survive being split across Tier 1 and Tier 2 (the hard one)

### Harness Matrix

| Harness | Server Mode | Web UI | Official Docker | MCP | Notes |
|---------|:---:|:---:|:---:|:---:|-------|
| **OpenCode** | ✅ Native (Hono+Effect) | ✅ SolidJS | ✅ | ✅ | Server-first architecture. Best tier-placement candidate. |
| **Claude Code** | ❌ CLI only | ❌ | ❌ | ✅ | Anthropic's official. Works directly on filesystem. No server, no web UI. |
| **Aider** | ❌ CLI only | ❌ | ❌ Community | ❌ | 46K stars, Apache 2.0. Operates on filesystem. Auto-commits to git. |
| **Cline / Roo Code** | ❌ VS Code ext | ❌ | ❌ | ✅ | IDE extension. Bound to VS Code runtime. |
| **Continue** | ❌ VS Code/JetBrains ext | ❌ | ❌ | ✅ | IDE extension. Read-only, mostly. |
| **Cursor** | ❌ IDE | ❌ | ❌ | ❌ | Full IDE. No way to extract it. |
| **OpenHands** | ✅ (Docker-isolated) | ✅ | ✅ | ✅ | Sandboxed agents. Heavy infrastructure. |
| **Codex CLI** | ❌ CLI only | ❌ | ❌ | ❌ | OpenAI's. Container-mode available. |
| **Gemini CLI** | ❌ CLI only | ❌ | ❌ | ✅ | Google's. |
| **Cody (Sourcegraph)** | ❌ IDE ext | ❌ | ❌ | ❌ | |
| **openclaw** | ❓ (need to research) | ❓ | ❓ | ❓ | Mentioned by user; unknown architecture. |

### Tier-Placement Patterns

Three distinct patterns emerge from the matrix:

#### Pattern 1: Server-First (OpenCode)

OpenCode is the only harness with a native server mode, web UI, and official Docker image. Its architecture is designed for network access: the server runs on a host, multiple clients (TUI, web, SDK) connect over HTTP. This maps directly onto Cove's two-tier model:

- **Tier 1 (laptop):** `opencode serve` in a container with bind-mounted code directory. Phone accesses via Tailscale.
- **Tier 2 (always-on):** Same container setup on the always-on box. Phone accesses via HTTPS at `opencode.cove`.

**The split-tier problem is unsolved** — sessions are local SQLite, files are on the host. But OpenCode is the *least bad* candidate for split-tier because its server-first design means a containerized instance on either tier behaves the same way. The operator connects to whichever is online.

#### Pattern 2: CLI with Filesystem Dependency (Claude Code, Aider, Codex CLI, Gemini CLI)

These harnesses are CLI-only, operate directly on the host filesystem, and have no server. They're excellent coding tools but architecturally hostile to remote access.

**Containerized deployment is straightforward** — bind-mount the project directory and the harness works inside the container just as it would on the host. But the CLI is still local; the operator must `docker exec` into the container to use it.

**Two ways to get a phone-accessible experience:**

1. **Web terminal in a container.** Run ttyd, Wetty, or similar in the same container as the harness. The harness stays CLI-only, but the operator gets a browser-based terminal at `claude.cove` that proxies into the container. This works for any CLI harness with zero changes to the harness itself. The cost: it's a terminal, not a polished web UI. The benefit: it works for everything.

2. **The harness gets a server (upstream or fork).** Claude Code may eventually ship a server mode; today it doesn't. Until then, Pattern 2 harnesses are tier-1-only via web terminal, or tier-2 with a phone-friendly terminal proxy.

**Split-tier viability:** Low. The harness's whole model is "I run here, on the host, with the files." A Tier-2 instance has no access to the Tier-1 filesystem unless the directory is shared (NFS, syncthing, git) — which defeats the point of having a local copy.

#### Pattern 3: IDE-Extension (Cline, Continue, Cody, Cursor)

These run inside VS Code, JetBrains, or a full IDE. They can't be extracted from the IDE runtime.

**Containerized deployment is impossible** without also containerizing the IDE (which defeats the purpose — the operator wants their own IDE, not a remote one).

**Tier placement:** Tier 1 only, on the operator's actual development machine. The phone-accessible experience comes from pairing the IDE with a remote-development extension (VS Code Remote, JetBrains Gateway) that proxies the IDE to a phone browser — but the latency is brutal and the UX is poor.

**Split-tier viability:** None. These are not Cove drop-ins; they're IDE drop-ins.

### Per-Harness Notes

#### OpenCode

- Tier 1: containerized, bind-mount code, expose 4096 via nginx + Tailscale.
- Tier 2: same container, different host. Phone reaches whichever is online.
- **Recommended.** Best fit for the two-tier model.

#### Claude Code

- CLI-only, no server. Operates on the host filesystem with full tool access.
- **Tier 1:** install directly on the laptop. Phone access via web terminal proxy (ttyd/wetty) in a container.
- **Tier 2:** viable as a containerized CLI, but the container must have the project files. Use git clones for offline, bind-mount for online. The operator runs `claude` inside the container.
- **Not split-tier.** Each instance is independent. No session sharing without a custom layer.

#### Aider

- Same shape as Claude Code. CLI-only, filesystem-direct, auto-commits to git.
- 46K stars, Apache 2.0, very stable.
- **Tier 1:** install on laptop, or run in a container with bind-mount.
- **Tier 2:** same — container with git clone of the project. Useful for unattended work (overnight builds, refactors on a Pi).
- **Not split-tier.** Sessions are per-process. No sync layer.

#### Cline / Roo Code

- VS Code extension. The harness *is* the IDE integration.
- **Tier 1 only.** No path to containerization that doesn't also containerize VS Code.
- **Not a Cove drop-in.** It's a VS Code drop-in.

#### OpenHands

- Sandboxed agent platform. Each agent runs in its own Docker container.
- Server mode + web UI. Heavy infrastructure (Postgres, Docker-in-Docker, separate backend/frontend).
- **Tier 2 candidate.** Designed for unattended agentic work. Operator submits a task, walks away, returns to a result.
- **Not tier 1.** The whole point is unattended operation; running it on a laptop is overhead without the benefit.
- **Not split-tier.** It's a tier-2-only service.

#### openclaw

- Mentioned by the operator. Not researched in depth. Treat as a Pattern 2 candidate (CLI with filesystem dependency) until proven otherwise.

### What "Connect To Directly" Means

The user's framing is right: **most harnesses can have containerized instances on Tier 1 and/or Tier 2 that you connect to directly.** The connection mode varies:

- **OpenCode:** HTTP, the server speaks the OpenCode API. Browser UI, SDK, or TUI client.
- **Claude Code / Aider / Codex / Gemini:** terminal (ttyd, wetty, gotty) over HTTPS. Or `docker exec` from a phone SSH client (Termux, Blink).
- **Cline / Continue / Cursor:** VS Code Remote / JetBrains Gateway. Slow, not recommended.
- **OpenHands:** HTTP, the OpenHands web UI. Submit tasks, review results.

The containerized instance is the same regardless of tier — the difference is which host runs the container and which files are bind-mounted.

### Why Not Force a Single Harness

Cove shouldn't pick one harness and force the operator to use it. Different tasks want different tools:

- **Quick edit, in-repo, while at the laptop:** Claude Code or Aider, direct on the host. No container overhead.
- **Unattended refactor on the always-on box:** OpenHands or a containerized Aider. Let it run overnight.
- **Phone-driven exploration:** OpenCode (web UI) or a web-terminal proxy into any CLI harness.
- **Heavy multi-file agentic work:** OpenCode (Tier 2) or OpenHands (Tier 2).

A Cove harness setup should support *all* of these without the operator having to think about it. That's the harbor principle: one command, the right tool is available.

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

### Multi-Harness Cove Service Pattern

For the broader harness catalog, a generalized compose template:

```yaml
# compose/harness/compose.yaml — parameterized for any harness
services:
  harness:
    image: ${HARNESS_IMAGE}  # e.g., ghcr.io/anomalyco/opencode, anthropic/claude-code, aider-ai/aider
    container_name: cove-${HARNESS_NAME}
    ports:
      - "127.0.0.1:${HARNESS_PORT}:${HARNESS_PORT}"
    volumes:
      - ${HARNESS_CODE_DIR}:/home/code:ro  # or :rw depending on harness
      - ~/Documents/cove/${HARNESS_NAME}:/home/${HARNESS_NAME}  # state persistence
    environment:
      - ${HARNESS_API_KEY}=${${HARNESS_API_KEY}}
    restart: unless-stopped
```

One compose file per harness, parameterized by `HARNESS_*` env vars. The operator runs `cove harness add claude` and gets a containerized Claude Code at `claude.cove`. Same for `aider`, `opencode`, etc.

### Open Questions

1. **Read-only vs read-write filesystem?** Read-only is safer but limits the agent. Read-write means the agent can modify files on the host.
2. **Which directories to mount?** `~/Documents/code/` covers Cove projects. What about other code locations?
3. **LLM API keys?** Stored in Vault, injected as env vars. The agent needs access to Anthropic/OpenAI APIs.
4. **Resource limits?** LLM calls are expensive. Need to prevent runaway token usage.
5. **Multiple projects?** OpenCode works on one project at a time. The web UI lets you switch, but sessions are per-project.
6. **Web terminal for CLI harnesses?** ttyd vs wetty vs gotty — which is the best fit for a phone browser? ttyd is the most popular and supports authentication.
7. **Split-tier for any harness?** OpenCode is the best candidate but unsolved. Should we wait for an upstream session-sync feature, or build it?
8. **OpenHands tier-2 deployment?** Worth the infrastructure overhead for unattended agentic work?
