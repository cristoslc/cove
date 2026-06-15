# Harness Catalog for Cove Integration — Trove Synthesis

## Key Findings

Cove tier-1 and tier-2 surfaces need AI coding harnesses, but only OpenCode has a native server architecture. For everything else, the deployment pattern is **containerize + bind mount** — bind mount is assumed for any containerized harness. Several harnesses now have web/remote control surfaces that change the deployment story:

1. **Claude Code Remote Control** (Feb 2026, research preview, v2.1.51+): bridges local Claude Code CLI to claude.ai/code web interface and the Claude mobile app. Outbound HTTPS only, no inbound ports. Files and MCP servers stay on the operator's machine.
2. **CloudCLI / claudecodeui** (siteboon, OSS): a desktop and mobile UI for Claude Code, OpenCode, Cursor CLI, Codex, and Gemini-CLI. Runs locally or remotely. Sandboxed agents with hypervisor-level isolation.
3. **ttyd** (tsl0922, 18K+ stars, C binary): "share your terminal over the web" — wraps any command in a web-based terminal served via WebSocket. Default port 7681. Basic auth, SSL support. The canonical web-shell bridge.
4. **OpenClaw** (formerly Clawdbot/Moltbot, 250K+ stars, Peter Steinberger, joined OpenAI Feb 2026): self-hosted, multi-channel AI agent. WhatsApp/Telegram/Slack/Discord/iMessage/Signal as UI. Local-first gateway, mobile nodes pair via WebSocket. Not a coding harness — a personal-assistant platform.
5. **swain-box** (~/code/swain-box/): the canonical reference pattern for kernel-isolated harness deployment. OpenCode server inside a Lima VM, behind Caddy on port 4097. 4 CPU / 4GiB RAM, mounts config (ro) and code (rw). VM is sole writer to opencode SQLite; host reads for ccusage.

## Architecture Patterns

### Pattern A: Server-First (OpenCode)

OpenCode's TUI is a client to a local HTTP server. The server is the primary surface; the TUI is one of many possible clients. Designed for containerization — `ghcr.io/anomalyco/opencode` is the official image.

- Tier-1: `opencode serve` on the laptop behind Caddy/nginx
- Tier-2: same image on always-online box, filesystem accessed via git sync
- Sessions: SQLite in a known mount; can be replicated (one writer rule)

### Pattern B: CLI with Filesystem Dependency + Bridge (Claude Code, Aider, Codex CLI, Gemini CLI)

The harness needs direct filesystem access to work. Containerize it; bind-mount the working directories. Provide a web/remote surface through one of:

- **Built-in remote control** (Claude Code: outbound bridge to claude.ai/code)
- **Third-party web shell** (ttyd, CloudCLI) wrapping the CLI
- **Third-party session UI** (CloudCLI for full session management)

Tier-1: container with bind mounts to `~/Documents/code` and `~/Documents/projects`
Tier-2: same image, but filesystem access is the hard problem (git sync or proxied I/O)

### Pattern C: IDE-Extension (Cline, Continue, Cursor)

Run inside an editor. No standalone server. Not a drop-in for Cove. Skip for tier-2.

### Pattern D: Local-First Agent Platform (OpenClaw)

Not a coding harness. A multi-channel personal-assistant platform with its own gateway, session model, and node pairing. Could be considered for tier-2 deployment if the operator wants 24/7 agent availability via messaging apps. But it competes with the forge/git-bug stack for the operator's attention and workflow.

## Tier Placement Matrix

| Harness | Tier 1 | Tier 2 | Notes |
|---------|:---:|:---:|-------|
| OpenCode | ✅ Native server | ✅ Git-sync | Already in swain-box pattern |
| Claude Code | ✅ Container + bind mount | ⚠️ Remote Control, but session must run locally | Files stay on operator's machine; outbound bridge |
| Aider | ✅ Container + bind mount | ⚠️ Git-sync only (auto-commits) | No session state — each invocation is stateless |
| Codex CLI | ✅ Container + bind mount | ⚠️ Same as Aider | Cloud-backed; tier-2 just runs the CLI |
| Gemini CLI | ✅ Container + bind mount | ⚠️ Same as Aider | Cloud-backed |
| Cline | ❌ IDE-only | ❌ | Skip |
| Continue | ❌ IDE-only, unmaintained | ❌ | Skip |
| Cursor | ❌ IDE-only | ❌ | Skip |
| OpenHands | ❌ | ✅ Sandbox agent platform | Designed for cloud/sandbox execution |
| OpenClaw | ⚠️ Possible | ✅ Self-host gateway | Different problem space — personal assistant, not coding |
| claudecodeui (CloudCLI) | ✅ Container | ✅ Container | Web UI for multiple harnesses |

## swain-box as Reference Pattern

swain-box is a real, working instance of the **kernel-isolated harness deployment** pattern:

- Lima VM (Apple VZ on macOS, QEMU on Linux) provides kernel isolation
- Caddy inside the VM on `:4097` reverse-proxies to `opencode serve` on `127.0.0.1:8848`
- Mounts are minimal: config ro, code rw, data rw
- VM is sole writer to `~/lima-opencode-data`; host reads for ccusage — no concurrent-write corruption
- Reduced from 8GiB → 4GiB after measurement (opencode is 1.31 GiB RSS, Caddy 34 MiB, Ubuntu idle ~300MB)

**The pattern is portable across harnesses.** Replace `opencode serve` with `claude` (with `--remote-control`), `aider`, or any CLI that can run inside a container with bind mounts. The Caddyfile, mount topology, and lifecycle are harness-agnostic.

**Cove integration question:** Does swain-box become a Cove service, or is it a reference pattern Cove mirrors?

Arguments for service:
- swain-box already has the deployment figured out (mounts, ports, lifecycle)
- `cove up` could include a `limactl start opencode-dev` step
- The Lima YAML + Caddyfile are versioned in swain-box; they'd move to cove

Arguments for reference pattern:
- swain-box is harness-specific (opencode) but the *pattern* is generic
- Cove's service model is Docker Compose / Colima containers, not Lima VMs
- swain-box could keep evolving independently; Cove just documents the pattern
- The Lima VM approach is heavier than necessary for most harnesses; Claude Code Remote Control means you don't need tier-2 for Claude at all

**Verdict:** Reference pattern, not service. Cove documents the pattern (kernel-isolated harness deployment) and provides a parameterized compose service for harnesses that don't have their own server (Claude Code, Aider, Codex CLI, Gemini CLI). OpenCode uses its native server (the swain-box pattern) or the same compose service. Operators who want kernel isolation use Lima manually; operators who want container isolation use Cove's compose.

## Deployment Recommendations

### Tier 1 (local laptop)

- **OpenCode**: native server on `:4096`, Caddy/nginx in front, served at `opencode.cove`. TUI is one client; web is another. Bind-mount `~/Documents/code` rw.
- **Claude Code**: container with bind mount, `claude --remote-control` running inside. The harness is the web surface (via claude.ai/code); no separate UI needed.
- **Aider, Codex CLI, Gemini CLI**: container with bind mount, no server. Web access via ttyd wrapping the CLI in tmux, or CloudCLI for session management.
- **OpenClaw** (if used): local install (npm), gateway on `:3000` or similar. Not a Cove service — different product.

### Tier 2 (always-online box)

- **OpenCode**: same container, git-sync filesystem access. Reference: swain-box (Lima VM) or compose with periodic git pull.
- **Claude Code**: not necessary. Remote Control bridges to the local CLI session; the operator's machine is the session host. Tier-2 doesn't add value.
- **Aider, Codex CLI, Gemini CLI**: stateless, can run on tier-2 with git-sync. Output is commits. Limited value — just runs in CI.
- **OpenClaw**: could be self-hosted on tier-2 for 24/7 availability via messaging apps. But this is a different use case than coding.

### The Phone Surface

- **OpenCode**: native web UI, first-class phone support
- **Claude Code**: claude.ai/code web + iOS/Android app, first-class
- **Others**: ttyd terminal in mobile browser, or CloudCLI's mobile UI
- **OpenClaw**: messaging apps — phone is the primary surface

## Sources

### Web sources (snapshotted)

- `claude-code-remote-control/` — code.claude.com official docs, v2.1.51+ feature
- `claudecodeui/` — siteboon/claudecodeui GitHub, multi-harness web UI
- `ttyd/` — tsl0922/ttyd GitHub, 18K+ stars, C binary
- `openclaw/` — openclaw/openclaw GitHub, 250K+ stars, Peter Steinberger

### Local sources (swain-box files)

- `swain-box/ARCHITECTURE.md` — system context, containers, mount topology
- `swain-box/PURPOSE.md` — single-line purpose
- `swain-box/AGENTS.md` — agent workflow notes
- `swain-box/TECH-STACK.md` — host, guest OS, toolchain
- `swain-box/DEVELOPER-WORKFLOWS.md` — VM lifecycle, data management
- `swain-box/USER-EXPERIENCE.md` — install, quality attributes
- `swain-box/opencode-dev.yaml` — Lima VM config
- `swain-box/Caddyfile` — reverse proxy config
- `swain-box/docs/musings/vm-disk-access-topology.md` — mount plan
- `swain-box/docs/musings/lighter-alternatives-to-8gb-vm.md` — VM sizing notes

## Gaps

- No first-hand test of Claude Code Remote Control — relying on official docs and third-party reviews
- CloudCLI integration with Cove's auth/nginx not validated
- OpenClaw self-hosting on tier-2 not evaluated
- ttyd's UX on mobile (keyboard, screen real estate) not tested
- swain-box is single-harness (opencode only); generalization to Claude Code is theoretical
