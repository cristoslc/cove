---
title: "AI-Git-Bot summary"
type: commentary
source: ai-git-bot-snapshot.md
fetched: 2026-10-14
---

# AI-Git-Bot — summary

**Why selected:** This is the single closest match to the operator's ask — a self-hosted, offline-capable bot that scans forge events, triages issues, refines them into structured work items, and dispatches a coding agent to implement issues as PRs. Written for exactly the gap: "most AI products focus primarily on GitHub."

**What it covers:**

- **Issue Triage workflow** ("Issue → Right Assignee"): on issue opened/assigned-to-bot, an LLM with an *editable routing prompt* reads the issue, picks exactly one assignee from configured accounts (person / bot / `none`), posts the routing reason as a comment, and assigns. Note: this triage is **routing**, not "pick agent-ready candidates" — that decision is made by *assigning the issue to the bot with the Coding Agent workflow*, i.e. assignment IS the dispatch mechanism.
- **Writer Agent workflow** ("Issue → Better Issue"): transforms rough issues into structured items with background/requirements/acceptance criteria/implementation notes — the "make it implementable" refinement step between triage and implementation.
- **Coding Agent workflow** ("Issue → Code"): issue assigned → clone → implement → run validation → open PR. The automated-implementation pipeline itself.
- **Pluggable issue workflows** (doc/ISSUE_WORKFLOWS.md) configured per bot — the extension surface where a custom "pick coding-agent candidates" scan could live.
- **Platforms:** Gitea is *production-ready* (GitHub/GHE too); GitLab/Bitbucket community; **Forgejo untested but implied by Gitea API compatibility**.
- **AI providers:** Anthropic, OpenAI + OpenAI-compatible, Gemini, **Ollama, llama.cpp** — local models explicitly supported; fits cove's LiteLLM proxy at `litellm.cove.local/v1`.
- **Ops:** single Docker image (multi-arch amd64/arm64), Docker Compose production deploy, Prometheus metrics endpoint, HMAC-signed outgoing webhooks with durable retry, AES-256-GCM secret encryption, HTTP-503 retry-with-backoff messaging.
- **License:** MIT. Multiple GitHub mirrors exist (bmseidel, jbcom, bjuraga, Postremus, bc3tech, myluoluo); badges and Docker image namespace point to `tmseidel/ai-git-bot` as canonical. Website: gitbot.eu.

**Cove relevance:** Highest of all candidates — it is the triage layer AND the issue→PR layer AND the writer/refinement layer in one self-hosted container. Open questions: (1) does the webhook + Gitea provider work against Forgejo 15.0.3 (gitea-1.22 API) — needs a probe like the pullfrog musing did; (2) its coding agent is its own LLM loop, not a bb/OpenCode harness dispatch; (3) triage prompt is routing-shaped, so "identify agent-ready candidates" would need a custom issue workflow or be driven by the Writer Agent's acceptance-criteria output.