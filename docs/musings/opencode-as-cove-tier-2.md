---
title: "AI Coding Harnesses as Cove Tier-1 Services"
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
  - **OpenCode data (rw):** persistent location for SQLite sessions, e.g. `~/Documents/cove/opencode` — must survive container restarts. The exact XDG path inside the container needs verification (see Open Questions).
  - **Config (rw):** `~/.config/opencode` — opencode.jsonc, MCP server definitions, AGENTS.md, custom commands. **OpenCode writes to this** (modifies config, adds skills, updates memories), so it must be rw. (Not ro as previously claimed.)

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
      # Config (rw) — opencode.jsonc, MCP defs, AGENTS.md, custom commands
      - ~/.config/opencode:/home/opencode/.config/opencode:rw
      # NOTE: ~/.agents/ and ~/.claude/ are NOT mounted. The user maintains
      # these as symlinks on the host for cross-tool skill sharing, but
      # OpenCode itself loads from ~/.config/opencode/. The swain-box pattern
      # mounts ~/.agents/ to make MCP filesystem tools serve those files;
      # for the OpenCode container directly, the operator should symlink
      # ~/.config/opencode/skills/ -> ~/.agents/skills/ on the host if
      # they want cross-tool skill sharing.
    environment:
      - OPENCODE_SERVER_USERNAME=${OPENCODE_SERVER_USERNAME:-opencode}
      - OPENCODE_SERVER_PASSWORD=${OPENCODE_SERVER_PASSWORD}
      - OPENCODE_SERVER_HOSTNAME=0.0.0.0
      - OPENCODE_SERVER_PORT=4096
    restart: unless-stopped
```

Behind nginx at `opencode.cove` with HTTPS, accessible from phone via Tailscale. See "Reverse Proxy (nginx)" below for why nginx (not Caddy) and how the auth bug interacts.

**What MVP explicitly is not:**
- No tier-2 deployment. OpenCode on the always-online box is v2.
- No Claude Code, Aider, Codex CLI, Gemini CLI, or OpenClaw. Other harnesses are v1+.
- No kernel isolation (Lima VM). Container isolation via Colima is sufficient for MVP.
- No MCP server allowlist mechanism beyond what OpenCode provides natively.

**Why OpenCode only for MVP:**
- It's the only harness with a native server mode — fits Cove's compose model without modification
- The operator already uses it (this musing's origin)
- **Non-portable by design:** MVP/v1 are bound to one machine. The SQLite session store in the data mount is not safe to sync across machines (concurrent-write corruption). Each tier-1 Cove is a single-machine deployment. Cross-machine session sync is v2 work.
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

## Claude Code — Local-Process Model, Fundamentally Different

Claude Code is **not a server-first architecture** like OpenCode. It is a local process that binds to its local environment: filesystem, API keys, terminal, MCP servers. There is no `claude serve` command. There is no HTTP API to call. The harness is the binary, and the binary runs on the machine with the files.

This is a fundamentally different architecture, and it has real consequences for tier-2:

- **No "deploy Claude Code to tier-2":** You can't put Claude Code on the always-online box and have it work, because the always-online box doesn't have the operator's files, API keys, or terminal.
- **Claude Code Remote Control (Feb 2026, v2.1.51+):** Anthropic shipped a bridge that exposes a *local* Claude Code session to claude.ai/code (web) and the Claude iOS/Android apps. **Files stay on the laptop.** The phone is a window into a session that runs on the machine with the files. This works for v1 — a Cove tier-1 install of Claude Code (`claude --remote-control`) gives phone access via claude.ai/code without modifying the architecture.
- **For tier-2 (v2), the options are:** (a) add an ACP (Agent Client Protocol) or similar server layer around Claude Code to make it remotely accessible, (b) accept that Claude Code is stuck on tier-1, and the workaround for "always-on Claude Code" is to make the tier-1 instance itself always-on (e.g., run it on a Proxmox VM in a closet), so there's no actual tier-2 deployment — just a tier-1 that happens to not sleep.

**Implication for Cove:** Claude Code v1 deployment is a container with `claude --remote-control`. No port mapping — uses outbound bridge to claude.ai/code. The session lives wherever the container runs, and the container must run on a machine with the operator's files. For tier-2, the path forward is either ACP wrapping or "make tier-1 always-on." Both are v2.

## Web UI Landscape (Comprehensively Crawled)

The musing's earlier version named only `ttyd`, `CloudCLI`, and Claude Code Remote Control as web surfaces. There are many more. The full evidence trail is in the [harness-catalog synthesis](../troves/harness-catalog/synthesis.md).

### OpenCode-Native UIs

| Project | Type | Notes |
|---------|------|-------|
| **OpenCode web** (`opencode web`) | Built-in | Alpha, mDNS for multiple instances. Auth has known bugs (see "Reverse Proxy (nginx)" below). |
| **CodeNomad** | Desktop + Server | "AI Coding Cockpit for OpenCode." Multi-instance, remote access, session management, voice input, git worktrees, sidecars (VSCode, ttyd). 1.9k stars, MIT, SolidJS. |
| **Palot** | Desktop (Electron) | Multi-agent GUI. Migrates from Claude Code/Cursor — converts configs, MCP servers, agents, commands, rules, hooks. |
| **opencode-gui** | Web | Multi-instance, multi-folder parallel execution. |
| **pk-opencode-webui** | Web | Prefix-aware (reverse-proxy friendly). Multi-project workspace, MCP management, Telegram bridge. |
| **opencode-manager** | Web (PWA) | Mobile-first. Push notifications, Bun+Hono, `ocm` CLI to attach local TUI to hosted server. |

### Generic Multi-CLI Dashboards

| Project | Supports | Notes |
|---------|----------|-------|
| **CloudCLI / claudecodeui** | Claude Code, OpenCode, Cursor CLI, Codex, Gemini | Web/GUI. Plugin system, sandboxed agents. |
| **AionUi** | Claude Code, Cursor CLI, Codex, Gemini | "Multi-CLI Swiss Army knife." |
| **ttyd** | Any CLI | Web-shell bridge. Default port 7681. Not harness-aware. |

### Claude Code-Specific UIs

| Project | Type | Notes |
|---------|------|-------|
| **Claude Code Remote Control** | Built-in | v2.1.51+, Feb 2026. Bridge to claude.ai/code + mobile apps. Outbound only. |
| **Nimbalyst** | Desktop GUI | Multi-session, visual editing. |
| **opcode** (winfunc) | Tauri 2 GUI | Custom agents, usage tracking. |
| **Claudeck** | Browser UI | Via Claude Code SDK. |
| **claude-dashboard** | TUI | k9s-inspired, manages multiple tmux sessions. |
| **Claudia GUI**, **claude-ui** | Desktop | Visual project management. |
| **Happy Coder** | Mobile | Encrypted, end-to-end. |

For Cove's MVP, the OpenCode web UI is the default. CodeNomad, Palot, pk-opencode-webui, opencode-manager are v1 candidates if the operator wants more than the default. CloudCLI is a v1 candidate for multi-harness dashboard.

## Reverse Proxy (nginx)

Cove already has an nginx reverse proxy (`compose/nginx/default.conf.j2`) with the following pattern for `git.cove` (Forgejo) and `vault.cove` (Vault):

```nginx
upstream forgejo_backend {
    server forgejo:3000;
}

server {
    listen 443 ssl;
    server_name git.cove cove;
    ssl_certificate     /certs/cove.local.pem;
    ssl_certificate_key /certs/cove.local-key.pem;

    location / {
        proxy_pass http://forgejo_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

**MVP: add an `opencode.cove` block** following this pattern:

```nginx
upstream opencode_backend {
    server opencode:4096;
}

server {
    listen 443 ssl;
    server_name opencode.cove;
    ssl_certificate     /certs/cove.local.pem;
    ssl_certificate_key /certs/cove.local-key.pem;

    location / {
        proxy_pass http://opencode_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

This solves multiple problems:
- TLS termination at nginx. OpenCode serves plain HTTP inside the container; nginx provides HTTPS.
- Consistent URL pattern (`*.cove`) alongside git.cove, vault.cove, hc.cove.
- Sets up the pattern for v1 harnesses: `claude.cove`, `aider.cove`, etc. all behind the same proxy.

**The user's reference to "Caddy" in the PR feedback was imprecise** — the actual reverse proxy in Cove is nginx, not Caddy (Caddy only exists in the swain-box repo, not in Cove itself).

### The OpenCode Web UI Auth Bug

There are multiple open issues confirming the OpenCode web UI's basic auth has been broken across several releases:

- [#9066](https://github.com/anomalyco/opencode/issues/9066) — "Failing to authenticate into web UI when username or password is set"
- [#18325](https://github.com/anomalyco/opencode/issues/18325) — "opencode-web Basic Auth Bug" (refreshing causes repetitive prompts)
- [#17376](https://github.com/anomalyco/opencode/issues/17376) — "Infinite Authentication Loop when opening Terminal in v1.2.25"
- [#8676](https://github.com/anomalyco/opencode/issues/8676) — Plugin client returns 401 when password is set (Desktop)
- [#9706](https://github.com/anomalyco/opencode/issues/9706) — Plugin client missing Authorization header

**Status:** all open, none closed. The basic auth implementation has been buggy for several releases.

**Cove mitigation:** nginx in front of OpenCode. The nginx proxy passes through to the OpenCode container. The basic auth happens inside OpenCode. If OpenCode's auth is buggy, the workaround is to **rely on nginx-level auth** (basic auth at the nginx layer, before proxying) or **Tailscale-only access** (no public-facing port, the phone must be on the Tailscale network to reach `opencode.cove`).

For MVP, **Tailscale-only is the recommended approach** — the laptop's Tailscale is already running, the phone is on Tailscale, the nginx server block is accessible from Tailscale peers. No public exposure. This sidesteps the auth bug entirely.

For v1 (or if the operator wants phone-on-cellular access), add nginx-level basic auth via `auth_basic` directive, with credentials in Vault.

## OpenCode Backend for v2 (Session Replication)

The user's question: does OpenCode support non-SQLite backends (e.g., Postgres) that would enable multi-way replication?

**Answer: no.** Confirmed by:

- [Issue #7840](https://github.com/anomalyco/opencode/issues/7840) (`sqlite vs embedded postgres`) was **closed** without implementation. OpenCode's stance: SQLite is sufficient for single-user local use; Postgres would add complexity without solving a real problem for MVP/v1.
- The third-party [`opencode-database-plugin`](https://github.com/aemr3/opencode-database-plugin) (aemr3) *logs* sessions/messages/tool executions/token usage to Postgres, but it does NOT replace the session store. OpenCode still uses SQLite for active session state. The plugin is a read-only mirror.
- OpenClaw has the same situation: issue #1568 requests Postgres+pgvector, open since Feb 2026, unimplemented.

**Implication for v2 session sync:**
- Can't do multi-master replication at the database layer (no CRDT, no Postgres backend)
- v2 options: (a) accept single-machine sessions, manual export/import between tier-1 and tier-2; (b) live-migrate during sync windows (pause session, copy SQLite, resume on tier-2); (c) build a sync layer on top of SQLite (last-writer-wins on individual fields, treat as event log)
- The closed issue + the plugin approach suggests v2 session sync is hard. Better to keep tier-2 as a fresh instance that imports from tier-1 on demand, or accept that the operator uses one machine at a time.

This is documented as a v2 research question. The MVP/v1 path is non-portable SQLite.

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
| **OpenCode** | **MVP** | ✅ Native server | ⏳ v2: git-sync (single-machine sessions) | Native web UI |
| **Claude Code** | v1 | ✅ Container + bind mount | ⏳ v2: ACP wrap or "always-on tier-1" | `claude.ai/code` via Remote Control |
| **Aider** | v1 | ✅ Container + bind mount | ⏳ v2: git-sync (auto-commits) | ttyd or CloudCLI |
| **Codex CLI** | v1 | ✅ Container + bind mount | ⏳ v2: same as Aider | ttyd or CloudCLI |
| **Gemini CLI** | v1 | ✅ Container + bind mount | ⏳ v2: same as Aider | ttyd or CloudCLI |
| **CodeNomad** | v1 | ✅ Desktop + server | ⏳ v2: same | Native desktop/server UI (multi-instance OpenCode cockpit) |
| **Palot** | v1 | ✅ Desktop | ⏳ v2: same | Native desktop UI (OpenCode) |
| **pk-opencode-webui** | v1 | ✅ Container | ⏳ v2: same | Native web UI (multi-project, MCP management) |
| **opencode-manager** | v1 | ✅ Container | ⏳ v2: same | PWA (mobile-first) |
| **CloudCLI** | v1 | ✅ Container | ⏳ v2: same | Native web UI (multi-harness) |
| **Cline** | — | ❌ IDE-only | ❌ | Editor |
| **Continue** | — | ❌ IDE-only, unmaintained | ❌ | Editor |
| **Cursor** | — | ❌ IDE-only | ❌ | Editor |
| **OpenHands** | — | ❌ | ⏳ v2: sandbox agent platform | Web |
| **OpenClaw** | — | ⚠️ Local install | ⏳ v2: self-host gateway | Messaging apps. See [`openclaw-as-cove-tier-2.md`](./openclaw-as-cove-tier-2.md) |

**Versioning:**
- **MVP** = the first thing shipped. One harness, proven end-to-end.
- **v1** = full tier-1 coverage. Multiple harnesses, all on the user workstation.
- **v2** = tier 2. Always-online box deployments, git-sync filesystem access, session replication.
- **—** = not in scope. IDE-only, unmaintained, or different product class.

## Deployment Recommendations

### MVP: OpenCode on Tier 1

See the [MVP Definition](#mvp-definition) section above for the compose service. Single harness, single tier, Docker via Colima. Plus an `opencode.cove` nginx server block (see [Reverse Proxy (nginx)](#reverse-proxy-nginx) above).

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

Phone access via claude.ai/code (web) or Claude mobile app. No port forwarding needed. The session lives wherever the container runs (the operator's laptop), not on tier-2.

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

**Tier 1 — CodeNomad (OpenCode cockpit):**

Either the desktop app or the server (`npx @neuralnomads/codenomad --password <pw> --launch`). For Cove integration, the server is the better fit — runs in a container, accessible at `codenomad.cove` via nginx proxy.

**Tier 1 — CloudCLI (multi-harness dashboard):**

A web UI that spans Claude Code, OpenCode, Cursor CLI, Codex, Gemini-CLI. Operators who want one dashboard for all harnesses add this in v1.

### v2: Tier 2 (always-online box)

- **OpenCode**: same container as v1, git-sync filesystem access. Compose with periodic `git pull` for filesystem changes. Session data on a known mount. **Sessions are non-portable in v2** (SQLite, single-machine per session). Manual export/import or live-migration during sync windows is the v2 path. See [OpenCode Backend for v2](#opencode-backend-for-v2-session-replication) above.
- **Claude Code**: needs ACP wrapping or "always-on tier-1" approach. See [Claude Code — Local-Process Model](#claude-code-local-process-model-fundamentally-different) above.
- **Aider, Codex CLI, Gemini CLI**: stateless, can run on tier-2 with git-sync. Output is commits. Limited value — just runs in CI.
- **OpenClaw**: self-host gateway on tier-2 for 24/7 availability via messaging apps. See [`openclaw-as-cove-tier-2.md`](./openclaw-as-cove-tier-2.md).

## Open Questions

MVP questions (must resolve before MVP ships):
1. **Exact XDG path inside the container?** The compose mounts `~/Documents/cove/opencode` to `/home/opencode/.local/share/opencode` — verify this matches where the OpenCode server actually writes. May need to check the official image's `USER` and `HOME` directives. **Spike: start the container, run a session, and `ls -la /home/opencode/.local/share/opencode/`.**
2. **Tailscale-only vs nginx basic auth for phone access?** Tailscale gives zero-config auth for the phone (if the phone is on the Tailscale network). Basic auth at nginx (`auth_basic`) works for any client. **MVP recommendation: Tailscale-only** — the laptop's Tailscale is already running, the phone is on Tailscale, no public exposure needed. Add nginx basic auth in v1 if cellular access is needed.
3. **Restart behavior on laptop wake — major risk.** When the laptop sleeps and wakes, does the OpenCode container restart cleanly? Sessions persist in the bind mount, so this should work, but the SQLite WAL needs to be consistent. **Spike: close the laptop lid for 5 min, open, check that the session is still accessible and the SQLite file isn't corrupted.** If SQLite is corrupted, the fix is to enable WAL checkpoint on graceful shutdown or use `litestream` for continuous backup.
4. **Resource limits (memory/CPU, not cost)?** We're using **Ollama Cloud**, not local Ollama — LLM calls are normal API calls, not expensive in the way local LLM inference is. Resource limits are about container protection (memory bounds for the LLM client process, CPU for MCP servers) — not about cost. Reasonable defaults: 2GiB memory limit, 1.0 CPU.

v1 questions (resolve before adding more harnesses):
5. **Bind-mount conflicts?** Multiple harnesses (OpenCode, Claude Code, Aider) all want `~/Documents/code` rw. Do they interfere, or can they coexist with the same mount? (Likely yes — they're separate processes reading the same tree.)
6. **Multi-harness dashboard integration?** Does CloudCLI / CodeNomad work behind Cove's nginx setup, or does it need its own routing? Likely yes for both.
7. **CodeNomad's `npx` execution model** — does it work cleanly inside a container with bind-mounted code dirs?

v2 questions (defer):
8. **Tier-2 session replication?** OpenCode is SQLite-only (issue #7840 closed without Postgres support). v2 options: accept single-machine sessions, manual export/import; live-migrate during sync windows; build sync on top of SQLite.
9. **Claude Code ACP layer?** Research whether ACP (Agent Client Protocol) can wrap Claude Code into a server. If yes, tier-2 is feasible. If no, "always-on tier-1" is the workaround.
10. **OpenClaw tier-2 use cases?** Self-host gateway for PR monitoring, daily standup, dependency triage. See [`openclaw-as-cove-tier-2.md`](./openclaw-as-cove-tier-2.md).

## Next Steps

MVP:
- **Spike: verify OpenCode data path** — start the container, run a session, check `/home/opencode/.local/share/opencode/`
- **Spike: laptop wake restart** — close lid 5 min, reopen, verify session persists and SQLite is consistent
- Add `opencode.cove` to `compose/nginx/default.conf.j2` (Ansible template)
- Write the `cove up` integration — add the opencode service to Cove's compose stack
- Test: create a session, restart the container, verify session persists
- Test: access from phone via Tailscale, verify web UI works
- Document the MVP deployment in the Cove install docs
- File issues for: (a) verifying XDG path inside container, (b) spike plan for laptop wake, (c) nginx template update

v1:
- Add Claude Code (Remote Control) — same bind-mount contract, different web surface (outbound)
- Add parameterized compose template for CLI harness pattern (Aider/Codex/Gemini with ttyd)
- Evaluate CodeNomad, Palot, pk-opencode-webui, opencode-manager as OpenCode UI alternatives
- Evaluate CloudCLI as a multi-harness dashboard
- Test multi-harness coexistence on the same laptop
- Research ACP for Claude Code (decides v2 path)

v2:
- Tier-2 OpenCode deployment (git-sync, single-machine sessions, manual export/import)
- Claude Code: either ACP wrapping or "always-on tier-1" Proxmox VM
- OpenClaw on tier-2 (per separate musing)
- swain-box Lima VM as a reference for operators who want kernel isolation

## Sources

Full evidence trail in [`docs/troves/harness-catalog/sources/`](../troves/harness-catalog/sources/):

**OpenCode UIs:**
- `codenomad/` — github.com/NeuralNomadsAI/CodeNomad, 1.9k stars, MIT
- `palot/` — github.com/ItsWendell/palot (Claude Code/Cursor → OpenCode migration)
- `pk-opencode-webui/` — github.com/prokube/pk-opencode-webui (prefix-aware, reverse-proxy friendly)
- `opencode-manager/` — github.com/chriswritescode-dev/opencode-manager (PWA)
- `opencode-web-docs/` — opencode.ai/docs/web (official docs)

**Claude Code UIs:**
- `claudecodeui/` — github.com/siteboon/claudecodeui (CloudCLI, multi-harness)
- `opcode/` — github.com/winfunc/opcode (Tauri 2 GUI)
- `claude-code-remote-control/` — code.claude.com official docs (v2.1.51+)

**Generic:**
- `ttyd/` — github.com/tsl0922/ttyd, 18k+ stars

**OpenCode backend & issues (referenced):**
- `opencode-sqlite-vs-postgres/` — issue #7840 (closed, no native Postgres)
- `opencode-auth-bug-18325/` — issue #18325 (basic auth bug, open)
- `opencode-auth-loop-17376/` — issue #17376 (infinite auth loop, open)

**Personal-assistant:**
- `openclaw/` — github.com/openclaw/openclaw, 250k+ stars

**Reference deployment (swain-box):**
- `swain-box/` — 10 files from ~/code/swain-box/ (ARCHITECTURE, PURPOSE, AGENTS, TECH-STACK, DEVELOPER-WORKFLOWS, USER-EXPERIENCE, opencode-dev.yaml, Caddyfile, plus 2 musings)

**Synthesis & related musings:**
- [`docs/troves/harness-catalog/synthesis.md`](../troves/harness-catalog/synthesis.md) — comprehensive evidence summary
- [`docs/musings/openclaw-as-cove-tier-2.md`](./openclaw-as-cove-tier-2.md) — separate musing on OpenClaw tier-2 fit
