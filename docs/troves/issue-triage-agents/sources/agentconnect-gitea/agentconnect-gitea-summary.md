---
title: "AgentConnect Gitea support — summary"
type: commentary
source: agentconnect-gitea-snapshot.md
fetched: 2026-10-14
---

# AgentConnect Gitea support — summary

**Why selected:** AgentConnect is a real, shipping product in the *harness-agnostic forge steward* category — the exact category the pullfork/pullfrog musing decided to hand-build. It shipped Gitea support 2026-09-13 (about a month before this research), which changes the build-vs-adapt calculus for cove.

**What it covers:**

- **Any agent harness:** Claude Code, Codex, Grok Build, DeepSeek, Pi, "or any ACP-compatible agent" — ACP is the same protocol family the operator's bb harness ecosystem speaks (bb has acp-provider skill). OpenCode compatibility is implicit via ACP.
- **Forge events → agent runs:** follow per-repository; start on new issues/PRs, updates, or @mention; **label-based trigger filters** (e.g. `bug`, `needs-review`) — "adding a matching label can start the agent". This is a hook point for triage-driven dispatch: a triage pass labels an issue, and the label starts the implementing agent.
- **Agents reply in forge:** comments, line comments for review, approve/request changes, commit status showing run state with session link.
- **Decision routing ("Jev-powered Decisions"):** route issues/PRs to specific agents based on content, including diff. E.g., "route bugs to a triage agent and security-related pull requests to a security reviewer"; cross-model review rules (Claude-written PRs → Codex runtime and vice versa).
- **Self-hosted:** open source (GitHub `agentconnect-md/agentconnect`, ~1.5k stars), Kubernetes chart install; Gitea 1.23+ required (cove runs Forgejo 15.0.3+gitea-1.22.0 — **below the stated 1.23 minimum**, needs verification against Forgejo's actual API surface).
- Also covers chat channels (Slack/Telegram/Discord/Lark/Google Chat) and Linear.

**Cove relevance:** Category-competitor to the hand-built forge steward from the Decided pullfrog musing. Strengths: agents are real harnesses (not bespoke loops), label-triggered dispatch maps cleanly onto "triage labels an issue → agent picks it up", multi-agent routing. Gaps vs the operator's ask: no *scheduled bulk back-log scan* (it's event/mention-driven, not a "drain the backlog" worker), and no built-in "coding-agent suitability" classification — that logic would live in the triage agent's prompt or a Decisions rule. Forgejo version floor (Gitea 1.23) is the main compatibility risk.