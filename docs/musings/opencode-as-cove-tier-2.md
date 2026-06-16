---
title: "AI Coding Harnesses and Cove's Scope"
created: 2026-06-13
revised: 2026-06-16
authored-by: cristos
status: Draft
---

# AI Coding Harnesses and Cove's Scope

## Why This Musing Exists

AI coding harnesses (OpenCode, Claude Code, Aider, etc.) all want filesystem access. The deployment question for Cove was: where does each harness run, how does the phone reach it, and does it need a tier-2 copy?

The answer, after building and testing the MVP: **Cove doesn't ship coding harnesses.** They're out of scope. This musing documents why — the experiment, the gaps discovered, and the decision to keep Cove as infrastructure and spin off a companion project for the development platform.

## The Experiment

We built a full OpenCode tier-1 service inside Cove's compose stack:

- `opencode` container (serve mode, port 4095)
- `caddy` container (bcrypt basic auth + `header_up Authorization` auth-bypass, port 4097)
- nginx `opencode.cove` server block (TLS termination)
- bringup playbook credential flow (1Password → bcrypt hash + base64 auth header → Caddyfile)
- mkcert SAN, /etc/hosts, health check

It worked. `https://opencode.cove/` served the OpenCode web UI through the full chain. Sessions persisted across container restarts. The auth-bypass trick worked around the OpenCode web UI auth bug.

But it also revealed fundamental gaps that made the container a **phone-access surface**, not a functional development environment.

## The Gaps

### Gap 1: The image doesn't run `serve` by default

The official `ghcr.io/anomalyco/opencode:latest` image has `ENTRYPOINT ["opencode"]` with no default `CMD`. Without `command: ["serve"]`, the container starts the TUI (which immediately exits in a headless container).

### Gap 2: HOME=/root, not the operator's HOME

The image runs as root. OpenCode looks for config at `$HOME/.config/opencode/` — which defaults to `/root/.config/opencode/`. Must set `HOME` to the operator's home directory explicitly.

### Gap 3: Config is a symlink farm

The operator's `~/.config/opencode/` is a directory of symlinks pointing to a dotfiles repo and `~/.agents/`. These symlinks are broken inside the container. Must mount the real config source and mount `~/.agents` at its absolute host path.

### Gap 4: host.docker.internal for local services

`localhost` inside the container is the container itself, not the host. Local Ollama, Vast GPU endpoints, and any other host-local service are unreachable without `extra_hosts: host.docker.internal:host-gateway`.

### Gap 5: No node/npx for MCP servers

The Alpine-based OpenCode image has no Node.js runtime. MCP servers defined as `npx` commands cannot start.

### Gap 6: API keys are 1Password refs, not values

The operator's `.env` file uses 1Password references (`op://...`). The container has no `op` CLI. Credentials must be injected at bringup time.

### Gap 7: Colima virtiofs blocks single-file bind-mounts

Colima's virtiofs filesystem driver rejects single-file bind-mounts. The Caddyfile must be baked into the Caddy image at build time rather than volume-mounted.

### Gap 8: OPENCODE_SERVER_PORT and OPENCODE_SERVER_HOSTNAME are ignored

These environment variables have no effect. Must use CLI flags instead.

### Gap 9: The container is not a development environment

**This is the fundamental gap.** OpenCode is not just a server — it's a development tool. When it runs a session, it executes `git`, `npx`, `uv`, `python`, `node`, and whatever else the operator's workflow requires. The official image is a bare Alpine server runtime. It has `git` and `bash`, but no `node`, `uv`, `python`, `npx`, `npm`, or any of the operator's toolchain.

The identity mounts solve the path problem (files are at the same absolute paths inside and out), but the toolchain problem is deeper: **the container needs to feel like the operator's machine.** Every binary the operator uses in a session must be present.

Options considered:
- **Custom Docker image** — add toolchain to the image. Maintenance burden: every new tool requires an image rebuild. macOS binaries can't run on Alpine.
- **Bind-mount host binaries** — doesn't work. macOS Mach-O binaries can't execute on Alpine Linux. Different ABIs.
- **Accept limitation** — container is phone-access surface only. Real development happens on the host. Two surfaces, one session store (identity mounts), but the container can't do everything the host can.
- **swain-box Lima VM** — full Ubuntu VM with the operator's toolchain. Solves everything at once. Costs 4GB RAM, VM startup time, heavier orchestration.

## The Decision

**Cove is infrastructure.** It provides forge, vault, CI, pages, DNS, reverse proxy. These are services that *support* development but don't *do* development. They're the plumbing.

**Coding harnesses, editors, LSPs, language runtimes are out of scope.** Once you add OpenCode, the question becomes: why not VSCode web? Why not LSP servers? Why not language runtimes? The scope expands naturally because a harness without a toolchain is a web UI with no engine. Cove's boundary is the harbor — services that run inside containers, wired together, with no manual assembly. Development tools don't fit that model. They need the host's toolchain, the host's filesystem, the host's identity.

**A companion project handles the development platform.** This is essentially swain-box expanded — a Lima VM with the full toolchain, coding harnesses, editors, LSPs, and remote access, packaged as a deployable service using Cove's model (compose, Ansible, 1Password/Vault for secrets). Cove provides the infrastructure the companion project connects to (git remotes, secrets, CI runners). The companion project provides the development surface.

## What Stays

The compose integration is removed from Cove. The experiment was valuable — it proved the patterns work (identity mounts, auth-bypass, credential injection, nginx routing) and it proved the toolchain gap is fundamental. The lessons are documented here for the companion project.

The harness catalog research stays. The trove (`docs/troves/harness-catalog/`) catalogs OpenCode, Claude Code, Aider, Codex CLI, Gemini CLI, and their web/remote surfaces. The synthesis (`docs/troves/harness-catalog/synthesis.md`) is a reference for the companion project.

The OpenClaw musing (`docs/musings/openclaw-as-cove-tier-2.md`) stays. OpenClaw is a personal-assistant platform, not a coding harness — it's a different category and may fit Cove's infrastructure model differently.

## Catalog of Harnesses (Reference)

### Pattern A: Server-First (OpenCode)

OpenCode's TUI is a client to a local HTTP server. The server is the primary surface; the TUI is one of many possible clients. Designed for containerization — `ghcr.io/anomalyco/opencode` is the official image. Sessions in SQLite.

For the companion project: identity mounts, Caddy auth-bypass, nginx TLS termination. The compose template from the experiment is a working starting point.

### Pattern B: CLI with Filesystem Dependency (Claude Code, Aider, Codex CLI, Gemini CLI)

The harness needs direct filesystem access to work. Containerize it; bind-mount the working directories. Web/remote access through built-in remote control (Claude Code), ttyd (web shell), or CloudCLI (multi-harness dashboard).

Claude Code is a local-process model — no `claude serve`, no HTTP API. Remote Control (v2.1.51+, Feb 2026) bridges a local session to claude.ai/code and mobile apps via outbound HTTPS. Files stay on the operator's machine.

### Pattern C: IDE-Extension (Cline, Continue, Cursor)

Run inside an editor. No standalone server. Not relevant for either Cove or the companion project.

### Pattern D: Local-First Agent Platform (OpenClaw)

Not a coding harness. A multi-channel personal-assistant platform (250K+ GitHub stars) with its own gateway, session model, and node pairing. WhatsApp/Telegram/Slack/Discord/iMessage/Signal as UI. Different product, complementary problem — OpenClaw handles recurring workflows (PR monitoring, daily standup, dependency triage) that don't need the operator present, then dispatches to coding harnesses for the actual work. See the [separate musing](./openclaw-as-cove-tier-2.md).

## Web UI Landscape

The harness-catalog trove has a comprehensive crawl of web/desktop UIs for OpenCode and Claude Code. Key projects:

**OpenCode-native:** CodeNomad (1.9k stars, multi-instance cockpit), Palot (Claude Code/Cursor migration), pk-opencode-webui (prefix-aware, MCP management), opencode-manager (PWA, mobile-first).

**Multi-CLI:** CloudCLI / claudecodeui (Claude Code, OpenCode, Cursor CLI, Codex, Gemini), AionUi, ttyd (18k+ stars, web-shell bridge).

**Claude Code-specific:** Remote Control (built-in, v2.1.51+), Nimbalyst, opcode (Tauri 2), Claudeck, claude-dashboard.

Full evidence in [`docs/troves/harness-catalog/synthesis.md`](../troves/harness-catalog/synthesis.md).

## Reverse Proxy (Caddy) — The Working Reference Pattern

The operator's host machine uses Caddy for OpenCode, not nginx. The pattern is:

- `opencode serve` on `127.0.0.1:4095` (internal)
- Caddy on `0.0.0.0:4096` (public-facing) with bcrypt basic auth
- `header_up Authorization "Basic {$OC_AUTH_B64}"` — the auth-bypass trick that works around OpenCode web UI auth bugs (#9066, #18325, #17376, #8676, #9706)
- Credentials from 1Password with 15-min cache
- Watchdog monitors server RSS, session-repair flow on restart

This pattern is the reference for the companion project. Cove's nginx is for Cove's own services (git.cove, vault.cove, hc.cove) — not for development tools.

## swain-box — The Reference Pattern

[`~/code/swain-box/`](https://git.cove/~/code/swain-box) is a real, working deployment of kernel-isolated harness deployment using OpenCode:

- Lima VM (Apple VZ on macOS, QEMU on Linux) provides kernel isolation
- Caddy inside the VM on `:4097` reverse-proxies to `opencode serve` on `127.0.0.1:8848`
- Identity mounts: config (ro), code (rw), data (rw)
- VM is sole writer to opencode SQLite; host reads for ccusage
- 4 CPU / 4GiB RAM

This is the starting point for the companion project. It solves the toolchain gap (full Ubuntu userspace), the virtiofs gap (Lima uses virtio-9p, not virtiofs), the symlink gap (real filesystem, not bind mounts), and the path-mapping gap (identity mounts) all at once.

## Open Questions (for the companion project)

1. **Toolchain provisioning** — what's the minimum set of binaries (node, uv, python, git, npx)? How are they installed and kept current?
2. **Multi-harness support** — does the VM run one harness or multiple? If multiple, how do they coexist (port conflicts, resource contention)?
3. **Tier-2 deployment** — can the VM pattern be deployed on an always-online box? What changes for git-sync filesystem access and session replication?
4. **Cove integration** — does the companion project use Cove's vault for secrets? Cove's forge for its own repo? Cove's nginx for TLS termination?
5. **Startup time** — Lima VM cold start is ~30s. Is that acceptable for a development surface, or does it need to be always-on?

## Sources

Full evidence trail in [`docs/troves/harness-catalog/sources/`](../troves/harness-catalog/sources/):

**OpenCode UIs:** codenomad, palot, pk-opencode-webui, opencode-manager, opencode-web-docs
**Claude Code UIs:** claudecodeui, opcode, claude-code-remote-control
**Generic:** ttyd
**OpenCode backend & issues:** opencode-sqlite-vs-postgres (#7840), opencode-auth-bug-18325, opencode-auth-loop-17376
**Personal-assistant:** openclaw
**Reference deployment:** swain-box (10 files)
**Working reference:** oc-zsh-functions (functions.opencode.zsh + Caddyfile)

**Synthesis & related musings:**
- [`docs/troves/harness-catalog/synthesis.md`](../troves/harness-catalog/synthesis.md)
- [`docs/musings/openclaw-as-cove-tier-2.md`](./openclaw-as-cove-tier-2.md)
