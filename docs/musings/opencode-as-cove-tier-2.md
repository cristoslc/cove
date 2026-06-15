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

## The Four Patterns

### Pattern A: Server-First (OpenCode)

OpenCode's TUI is a client to a local HTTP server. The server is the primary surface; the TUI is one of many possible clients. Designed for containerization — `ghcr.io/anomalyco/opencode` is the official image. Sessions in SQLite.

This is the only harness that fits the Cove service model without modification. It's also the only one where tier-2 is genuinely useful (the server can run anywhere, session state is a known mount).

### Pattern B: CLI with Filesystem Dependency (Claude Code, Aider, Codex CLI, Gemini CLI)

The harness needs direct filesystem access to work. Containerize it; bind-mount `~/Documents/code` and `~/Documents/projects`. The CLI is the entry point; web/remote access is bolted on through one of:

- **Built-in remote control** (Claude Code v2.1.51+, Feb 2026)
- **Third-party web shell** (ttyd wrapping the CLI in tmux)
- **Third-party session UI** (CloudCLI / siteboon/claudecodeui for full session management across Claude Code, OpenCode, Cursor CLI, Codex, Gemini-CLI)

For tier-2, these harnesses are mostly stateless — each invocation reads the working tree, does work, writes commits. Filesystem access on tier-2 is the hard problem (git sync or proxied I/O).

### Pattern C: IDE-Extension (Cline, Continue, Cursor)

Run inside an editor. No standalone server. Not a drop-in for Cove. Skip for tier-2.

### Pattern D: Local-First Agent Platform (OpenClaw)

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

### Claude Code UI (claudecodeui)

Same project (the README uses both names). Live projects, session history, mobile-friendly.

## swain-box — The Reference Pattern

[`~/code/swain-box/`](https://git.cove/~/code/swain-box) is a real, working deployment of **kernel-isolated harness deployment** using OpenCode:

- Lima VM (Apple VZ on macOS, QEMU on Linux) provides kernel isolation
- Caddy inside the VM on `:4097` reverse-proxies to `opencode serve` on `127.0.0.1:8848`
- Mounts: `~/.agents`, `~/.claude`, `~/.config/opencode` (ro); `~/Documents/code`, `~/Documents/projects`, `~/lima-opencode-data` (rw)
- VM is sole writer to `~/lima-opencode-data`; host reads for ccusage — no concurrent-write corruption
- 4 CPU / 4GiB RAM (reduced from 8GiB after measurement: opencode 1.31 GiB RSS, Caddy 34 MiB, Ubuntu idle ~300MB)

**The pattern is portable across harnesses.** Replace `opencode serve` with `claude --remote-control`, `aider`, or any CLI. The Caddyfile, mount topology, and lifecycle are harness-agnostic.

**Full evidence:** [`swain-box/`](../troves/harness-catalog/sources/swain-box/) in the harness-catalog trove.

## Does swain-box Become a Cove Service?

Arguments for making it a Cove service:
- swain-box already has the deployment figured out (mounts, ports, lifecycle)
- `cove up` could include a `limactl start opencode-dev` step
- The Lima YAML + Caddyfile are versioned in swain-box; they'd move to cove

Arguments for keeping it as a reference pattern:
- swain-box is harness-specific (opencode) but the *pattern* is generic
- Cove's service model is Docker Compose / Colima containers, not Lima VMs
- swain-box can keep evolving independently; Cove just documents the pattern
- The Lima VM approach is heavier than necessary for most harnesses; Claude Code Remote Control means you don't need tier-2 for Claude

**Verdict:** Reference pattern, not service. Cove documents the pattern and provides parameterized compose services for harnesses. Operators who want kernel isolation use Lima manually; operators who want container isolation use Cove's compose.

## Tier Placement Matrix

| Harness | Tier 1 | Tier 2 | Web Surface |
|---------|:---:|:---:|-------------|
| **OpenCode** | ✅ Native server | ✅ Git-sync | Native web UI |
| **Claude Code** | ✅ Container + bind mount | ⚠️ Files stay on laptop | `claude.ai/code` via Remote Control |
| **Aider** | ✅ Container + bind mount | ⚠️ Git-sync (auto-commits) | ttyd or CloudCLI |
| **Codex CLI** | ✅ Container + bind mount | ⚠️ Same as Aider | ttyd or CloudCLI |
| **Gemini CLI** | ✅ Container + bind mount | ⚠️ Same as Aider | ttyd or CloudCLI |
| **Cline** | ❌ IDE-only | ❌ | Editor |
| **Continue** | ❌ IDE-only, unmaintained | ❌ | Editor |
| **Cursor** | ❌ IDE-only | ❌ | Editor |
| **OpenHands** | ❌ | ✅ Sandbox agent platform | Web |
| **OpenClaw** | ⚠️ Local install | ✅ Self-host gateway | Messaging apps |
| **CloudCLI** | ✅ Container | ✅ Container | Native web UI |

## Deployment Recommendations

### Tier 1 (local laptop)

```yaml
# OpenCode — native server, compose service
services:
  opencode:
    image: ghcr.io/anomalyco/opencode:latest
    ports: ["127.0.0.1:4096:4096"]
    volumes:
      - ~/Documents/code:/home/code:rw
      - ~/Documents/projects:/home/projects:rw
      - ~/Documents/cove/opencode:/home/opencode:rw
    environment:
      - OPENCODE_SERVER_PASSWORD=${OPENCODE_SERVER_PASSWORD}
    restart: unless-stopped
```

Behind nginx at `opencode.cove` with HTTPS, accessible from phone via Tailscale.

```yaml
# Claude Code — container with bind mount, Remote Control for web
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

```yaml
# Aider, Codex CLI, Gemini CLI — container with bind mount, ttyd for web
services:
  aider:
    image: python:3.12-slim
    command: ttyd -p 4097 -c ${AIDER_USER}:${AIDER_PASS} aider --model sonnet
    volumes:
      - ~/Documents/code:/home/code:rw
    ports: ["127.0.0.1:4097:4097"]
```

Phone access via `https://aider.cove` (nginx in front of ttyd).

### Tier 2 (always-online box)

- **OpenCode**: same container, git-sync filesystem access. Reference: swain-box pattern (Lima VM) or compose with periodic `git pull`. Session data on a known mount.
- **Claude Code**: not necessary. Remote Control bridges to the local CLI session. Tier-2 doesn't add value — the session must run on a machine with filesystem access.
- **Aider, Codex CLI, Gemini CLI**: stateless, can run on tier-2 with git-sync. Output is commits. Limited value — just runs in CI.
- **OpenClaw**: could be self-hosted on tier-2 for 24/7 availability via messaging apps. Different use case than coding.

## Hardening: Should Cove Adopt the swain-box Pattern?

The previous section said "reference pattern, not service." That was about whether to bundle Lima VM orchestration into `cove up`. A separate question: should Cove *adopt* the swain-box pattern as the recommended tier-1 deployment, for hardening reasons?

### Threat Model

What are we actually hardening against?

| Threat | Mitigation |
|--------|-----------|
| Compromised MCP server (executes arbitrary code) | Process isolation: container, VM |
| Prompt injection → malicious tool calls | Tool allowlist, not isolation |
| Compromised harness install (npm/pip supply chain) | Same: process isolation |
| Stolen laptop | Full-disk encryption (FileVault/LUKS) |
| Compromised LLM API key | API rate limits, key rotation |
| Kernel exploit from inside harness | Kernel isolation: VM |

The first three are the realistic threats. Prompt injection is the most common — an LLM that exfiltrates env vars, writes to `~/.ssh/`, or runs `curl | sh`. The harness executes whatever the LLM decides to call. If the harness has host filesystem access (bind mount rw), so does the injection.

### Isolation Layers

| Layer | Provides | Cost | swain-box status |
|-------|----------|------|------------------|
| Bare host (no isolation) | None | Free | Not used |
| Docker container | Process + filesystem + network | ~50MB overhead | Not used |
| Colima (Lima + Docker) | Same as Docker | ~300MB idle, macOS native | Available, not default |
| Lima VM (no Docker) | Separate kernel | 1.7 GiB idle, 4 GiB allocated | **Current** |
| Hardware VM (KVM, Hyper-V) | Separate kernel + firmware | Full hypervisor, 8+ GiB | Not used |

**The gap is between Colima and Lima VM.** Docker gives you process isolation. A container escape CVE means host kernel access — rare, but real (CVE-2024-21626 etc.). Lima VM gives you a separate kernel. No process can escape a VM to the host without a kernel exploit in the hypervisor (Apple VZ or QEMU), which is a much smaller attack surface.

### What swain-box Actually Buys You

Running OpenCode in a Lima VM means:
- MCP servers run inside the VM, not the host
- Filesystem access is via 9p/virtiofs mounts, not direct host fs
- A compromised harness or MCP server can't `rm -rf ~/Documents/code` on the host
- Network namespace is isolated (the VM has its own network stack)
- ccusage (host) reads SQLite from a shared mount — VM is sole writer, no corruption

**For MCP server security specifically:** MCP servers are the highest-risk surface. They're npm/pip packages that the LLM invokes. A prompt-injected server can `process.exit(0)` after `exec("rm -rf /")`. In a container, that wipes the container. In a Lima VM, it wipes the VM's filesystem. In neither case does it touch the host. **Both are acceptable outcomes** — the damage is contained.

The difference is: if the attacker pivots inside the container (via CVE), they reach the host kernel. From a Lima VM, they have to escape the VM entirely, which is a much higher bar.

### What It Costs

- **Operational complexity**: `brew install lima`, `limactl start/stop`, separate lifecycle from `cove up`
- **Resource overhead**: 4 GiB RAM allocated, 1.7 GiB actual usage. On an 8 GiB laptop, this is half the memory.
- **Mount friction**: 9p/virtiofs is slower than native fs. Large git operations feel sluggish inside the VM.
- **Single-harness proven**: swain-box works for OpenCode. Generalizing to Claude Code (with Remote Control), Aider, etc. is theoretical — would need new Lima YAMLs.

### Recommendation

**Document swain-box as the hardened tier-1 option, not the default.** Three tiers of isolation, three deployment stories:

1. **Default (Cove Compose)**: OpenCode + harnesses in Docker containers via Colima. Process isolation, shared kernel. Sufficient for most operators.
2. **Hardened (swain-box / Lima VM)**: OpenCode in a Lima VM. Kernel isolation, separate filesystem, MCP server containment. For operators who care about prompt injection pivoting to kernel exploits.
3. **Remote (Claude Code Remote Control)**: No local process — claude.ai/code is the window, the laptop is the host. Hardened by definition: nothing to compromise locally except the session.

The operator picks. `cove up` does the default. `cove up --hardened` does Lima VM setup. `cove up --remote` configures Claude Code for Remote Control.

**For most operators, the right answer is the default.** Prompt injection is the realistic threat, and tool allowlists handle that. Kernel isolation is defense-in-depth for a low-probability, high-impact scenario.

**For operators who explicitly accept MCP server risk** (running third-party MCP servers, or MCP servers from untrusted sources), the Lima VM pattern is worth the operational cost.

### What This Means for swain-box

swain-box stays as a standalone repo at `~/code/swain-box/`. Cove:
1. Documents the pattern (this musing)
2. Provides a `--hardened` flag that links to swain-box's Lima YAML
3. Does not maintain the Lima YAML itself — swain-box owns the deployment
4. Tracks the swain-box repo as a reference; operators clone and follow its docs

This keeps swain-box evolving independently (its own concerns: Apple VZ vs QEMU, mount topology, ccusage integration) while making the pattern available to Cove operators.

## Open Questions

1. **Lima VM vs Docker container for kernel isolation?** swain-box uses Lima. Cove uses Colima (Docker). The answer above: both, with `--hardened` flag for Lima.
2. **Multiple harnesses on the same laptop?** Can OpenCode and Claude Code coexist? They both want `~/.claude` and `~/.config/opencode` mounts. Conflicts?
3. **Session sharing across harnesses?** CloudCLI promises multi-harness session management. Does that actually work in practice?
4. **Tailscale vs nginx auth?** Tiers 1 and 2 both expose web surfaces. Tailscale gives zero-config auth. nginx + basic auth + TLS gives broader access. Which to standardize on?
5. **Resource limits per harness?** LLM calls are expensive. Need per-harness rate limits or token budgets.
6. **OpenClaw integration?** The user mentioned it as a possible drop-in. Should Cove provide a tier-2 OpenClaw service, or is it out of scope?
7. **MCP server allowlist as first-line defense?** If we restrict which MCP servers can be invoked, the kernel isolation question becomes academic. What's the allowlist story?

## Next Steps

- Pick the v1 harness set: OpenCode (native) + Claude Code (Remote Control) covers most needs
- Write a parameterized compose template for the CLI harness pattern (Aider/Codex/Gemini)
- Test Claude Code Remote Control on the local laptop
- Evaluate CloudCLI as a multi-harness dashboard
- Document the Lima VM pattern in the swain-box repo so operators can replicate
- Decide: should `cove up` include Lima VM setup, or only Compose services?
- Build `cove up --hardened` flag that points to swain-box's Lima YAML
- Define MCP server allowlist mechanism (first-line defense before isolation matters)

## Sources

Full evidence trail in [`docs/troves/harness-catalog/sources/`](../troves/harness-catalog/sources/):

- `claude-code-remote-control/` — code.claude.com official docs, snapshotted
- `claudecodeui/` — siteboon/claudecodeui GitHub
- `ttyd/` — tsl0922/ttyd GitHub
- `openclaw/` — openclaw/openclaw GitHub
- `swain-box/` — 10 files from ~/code/swain-box/ (ARCHITECTURE, PURPOSE, AGENTS, TECH-STACK, DEVELOPER-WORKFLOWS, USER-EXPERIENCE, opencode-dev.yaml, Caddyfile, plus 2 musings)

Synthesis: [`docs/troves/harness-catalog/synthesis.md`](../troves/harness-catalog/synthesis.md)
