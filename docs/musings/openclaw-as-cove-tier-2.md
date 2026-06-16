---
title: "OpenClaw as a Cove Tier-2 Service"
created: 2026-06-15
authored-by: cristos
status: Draft
---

# OpenClaw as a Cove Tier-2 Service

## What is OpenClaw?

OpenClaw (formerly Clawdbot, Moltbot) is a self-hosted, multi-channel personal AI assistant. Created by Peter Steinberger, who joined OpenAI in Feb 2026. 250k+ GitHub stars.

It connects to messaging platforms (WhatsApp, Telegram, Slack, Discord, iMessage, Signal, Matrix, Teams, WeChat, etc.) and acts on the operator's behalf: shell commands, browser automation, file operations, email, calendar. Local-first gateway — single control plane for sessions, channels, tools, events. Mobile nodes (iOS/Android) pair via WebSocket.

**Key difference from coding harnesses:** OpenClaw is a personal-assistant platform, not a coding tool. The operator doesn't ask it to "fix the memory leak" — they ask it "monitor PR comments and spin up a coding agent when one needs review."

## Why this is a separate problem

The harness catalog musing dismissed OpenClaw as "different product, different problem." That framing was lazy. OpenClaw addresses a *complementary* problem to coding harnesses: **recurring workflows that don't require the operator to be present.**

Concretely:

- **PR review monitoring:** "When a PR is opened or updated, have OpenClaw ping me on Telegram, and if I don't respond in 30 min, have it spin up a Claude Code session to do a first-pass review and post the result as a comment."
- **Daily standup prep:** "Every morning at 9am, summarize the merged PRs and open issues across my projects, and post to Slack."
- **Dependency update triage:** "When a Dependabot PR opens, check the changelog, run the tests, and post a recommendation."
- **Inbox triage:** "Read new emails, categorize, draft replies, and ping me for the ones that need my input."

These are workflows where the operator wants an agent to be **continuously running** and **reactively triggered** by external events. Coding harnesses are interactive — you start a session, you work, you end. OpenClaw is a daemon that watches and acts.

## Tier-2 fit

OpenClaw is a strong fit for tier-2 (always-online box):

- **Local-first but always-on:** OpenClaw's gateway needs to stay up. A laptop that sleeps is a problem. Tier-2 doesn't sleep.
- **Multi-channel inbox:** WhatsApp/Telegram/Slack/Discord/iMessage/Signal are all things the operator wants to reach on their phone. OpenClaw bridges phone → tier-2.
- **Reactive workflows:** Webhooks from Forgejo (PR opened), cron (daily standup), or external APIs (email arriving). Tier-2 receives the events.
- **Coding agent handoff:** OpenClaw can spin up coding agents (Claude Code, OpenCode) on demand. Tier-2 has the resources to run them.

## Deployment model

A tier-2 OpenClaw service in Cove would look like:

```yaml
# compose/openclaw/compose.yaml
services:
  openclaw:
    image: openclaw/openclaw:latest
    container_name: cove-openclaw
    restart: unless-stopped
    ports:
      - "127.0.0.1:7777:7777"  # gateway web UI
    volumes:
      - ~/Documents/cove/openclaw:/home/openclaw/.openclaw:rw
      - ~/Documents/code:/home/code:ro  # can read repos for context
      - ~/.config/opencode:/home/opencode/.config/opencode:ro  # for handoff
    environment:
      - OPENCLAW_GATEWAY_PORT=7777
      - OPENCLAW_LOG_LEVEL=info
    # No exposed port for messaging — outbound to WhatsApp/Telegram APIs
```

The operator configures channel connections (WhatsApp via QR scan, Telegram bot token, etc.) through the gateway UI. The gateway holds those connections open on tier-2.

## Handoff to coding harnesses

The interesting case is when OpenClaw wants to do coding work. Two patterns:

1. **OpenClaw → OpenCode:** OpenClaw has the OpenClaw SDK. If the operator has an OpenCode instance running on tier-2 (or accessible via Tailscale), OpenClaw can call `client.session.create()` and `client.session.prompt()` directly. The session runs in the OpenCode instance, OpenClaw monitors events.
2. **OpenClaw → Claude Code:** Harder. Claude Code is a local process model, no server. OpenClaw would need to either (a) run Claude Code itself in a subprocess and pipe stdin/stdout, or (b) use Claude Code Remote Control via the operator's MacBook (if online). (a) is more reliable; (b) is the existing pattern.

The swain-box-style Lima VM for OpenClaw is overkill — OpenClaw already has its own isolation story (MCP servers, node pairing, local-first gateway). Containers in Colima are sufficient.

## What it doesn't do

OpenClaw is not a replacement for coding harnesses. It doesn't:
- Have a TUI for interactive coding sessions
- Edit files with diff previews
- Run tests in a sandbox with permissions
- Integrate with IDEs (VS Code, JetBrains)

It complements them. The operator uses OpenClaw for "what's happening in my projects" and dispatches to Claude Code/OpenCode for "do this work."

## Open questions

1. **Storage backend:** OpenClaw uses SQLite by default. Same portability problem as OpenCode. Issue #1568 (Postgres+pgvector) is open but unimplemented.
2. **Channel security:** WhatsApp/Telegram bots hold session tokens. Compromised OpenClaw = compromised messaging identity. Threat model for tier-2.
3. **Resource limits:** OpenClaw runs continuously. Memory/CPU on tier-2 needs bounds. 1-2 GB typical, but spikes during PR review workflows.
4. **How does OpenClaw know about Cove projects?** Does it need to read git remotes from `~/Documents/code/`? Or does Forgejo webhooks tell it when a PR opens? The latter is cleaner.
5. **Multi-operator support:** OpenClaw is single-user. Cove's "one operator" worldview aligns. No issue.

## Next steps

- Trial: install OpenClaw on a spare tier-2 box, connect WhatsApp, configure a PR-monitor workflow
- Evaluate whether OpenClaw + OpenCode is the right handoff pattern, or if OpenClaw + Claude Code (subprocess) is more reliable
- Decide: does Cove provide a first-class `cove up openclaw` service, or document OpenClaw as operator-installed?
