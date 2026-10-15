# Synthesis: Issue Triage Agents (Forgejo / offline-first)

Collected 2026-10-14 to answer: *what tooling exists to scan forge issues, triage them, and identify candidates for automated implementation with a coding agent — offline-first, compatible with cove's Forgejo at `git.cove.local`?*

Related prior work in this repo: `docs/musings/2026-08-28-pullfrog-forgejo-adaptation.md` (Decided — forge-steward for PR review; hybrid lift/rewrite plan) covers the PR-review side of the same architecture; this trove covers the issue-triage / issue→PR side. Related troves: `forgejo-pr-mirror`, `harness-catalog`.

## The pipeline decomposes into three stages

Stage 1 — **Scan** (list open issues; batch/cheap). Stage 2 — **Triage** (classify, priority, dedupe, needs-info gate, and the key output: *coding-agent suitability*). Stage 3 — **Implement** (label/assign dispatches a coding agent that opens a draft PR with self-review). No single surveyed tool is best at all three; the candidates cluster by stage strength.

## Candidates by shape

| Candidate | Stage strength | Forgejo | Offline | License | Harness |
|---|---|---|---|---|---|
| **ai-git-bot** (`tmseidel/ai-git-bot`, MIT, Docker) | triage (routing), refine (Writer Agent), implement (issue→PR), PR review | Gitea production-ready; Forgejo untested (Gitea API) | Ollama/llama.cpp/OpenAI-compatible → can point at cove LiteLLM | MIT | own LLM workflow loop (not bb/OpenCode) |
| **AgentConnect** (`agentconnect-md/agentconnect`, ~1.5k★) | event/mention-driven agent dispatch; label-filtered triggers; content-based routing (Decisions) | Gitea 1.23+ (cove runs gitea-1.22.0 base — below stated floor) | self-hosted k8s chart | open source | **any harness — Claude Code, Codex, Pi, any ACP-compatible (OpenCode via ACP)** |
| **forgejo-mcp** (`raohwork/forgejo-mcp`, MPL-2.0, Go) | full issue tool surface (labels, comments, blocking, milestones) as MCP tools | **Forgejo first-class** | stdio/HTTP local, docker | MPL-2.0 | any MCP client (bb/OpenCode) |
| **PR-Agent** (`The-PR-Agent/pr-agent`, Apache-2.0) | `similar_issue` duplicate/related detection; cheap single-LLM-call tools | Gitea ✅ (some features degraded) | LiteLLM → any provider incl. Ollama | Apache-2.0 (community-owned now) | fixed CLI tools |
| **DevIntern** (`getdevintern/devintern`, FSL-1.1) | backlog-drain worker: `task_query` polling → self-reviewed PRs; vague → questions; bounce-back semantics; Sentry → bugfix PRs | **no Forgejo/Gitea tracker**; Jira/Linear/GitHub/Trello/Asana/ADO/markdown | self-hosted, local keys | FSL-1.1 (Apache-2.0 in 2y); daemon paid | Claude Code/Codex/Cursor/**OpenCode** |
| **gh-aw AI issue triage** (`github/gh-aw` gallery) | the *pattern spec*: completeness → spam gate → type/priority → duplicate-vs-related → **coding-agent suitability (Suitable / Needs more info / Needs maintainer judgment)** → one report; read-only agent + safe-outputs writes, allowlisted labels, max-output caps | GitHub Actions only | n/a (pattern) | MIT (pattern copyable) | Copilot/Claude/Codex/Gemini engines |

## Key findings across sources

1. **The triage pass is a prompt pattern, not a product.** GitHub's gh-aw `issue-triage.md` sample is the open, copyable state of the art: completeness gate → spam gate → type/priority with consistent definitions → duplicate vs related (never on title similarity alone, max 3, cite numbers) → **coding-agent suitability classification** → one concise report. Every deployment path below can reuse this prompt shape verbatim.
2. **"Triage" splits into two different jobs.** ai-git-bot's Issue Triage is *routing* (pick one assignee, post reason). The operator's ask — "identify good candidates for automated implementation" — is the *suitability* job from the gh-aw pattern (Suitable / Needs more info / Needs maintainer judgment). Tools conflate them; the suitability gate is the piece worth building.
3. **Assignment-as-dispatch is the established dispatch contract.** ai-git-bot dispatches implementation when an issue is assigned to a bot with the Coding Agent workflow; AgentConnect starts agents on label-filtered events ("adding a matching label can start the agent"). Both mean triage stage 2 can dispatch stage 3 with nothing but a forge write (assign/label) — a write that stays forge-side and auditable.
4. **The scheduled scanner variant exists in the wild** ("Issue Monster": wake every ~40 min, score open issues, ensure candidates are distinct, hand the best to the coding agent, cheap-model posture flagged by audit tooling) and in DevIntern's worker (`task_query` + poll_interval + one-at-a-time pipeline). A backlog drain is a cron + query + queue, not new architecture.
5. **Duplicate detection has a working open implementation**: PR-Agent's `similar_issue` (CLI-callable, ~single LLM call). gh-aw's approach is embedding-free: instruct the agent to search the tracker and apply `duplicate` only at high confidence.
6. **Every serious candidate is harness-agnostic on the agent side but GitHub-or-Gitea-shaped on the forge side.** Forgejo compatibility is "Gitea API-compatible, untested" everywhere except forgejo-mcp (Forgejo-first). The pullfrog musing already established the probe recipe (`git.cove/swagger.v1.json`, REST-only, base `/api/v1`).
7. **Offline-first holds best through OpenAI-compatible endpoints.** ai-git-bot (Ollama/llama.cpp/OpenAI-compatible), PR-Agent (LiteLLM), and gh-aw engines all accept a proxy URL — cove's LiteLLM service at `litellm.cove.local/v1` is the integration point. AgentConnect and DevIntern run *harnesses* (Claude Code/OpenCode), where offline-ness is the harness provider's property, not the tool's.

## Points of tension

- **Buy vs compose:** ai-git-bot is a turnkey all-in-one (but its coding agent is its own loop, and Forgejo support is unprobed); the compositional path (forgejo-mcp + bb thread + gh-aw prompt pattern) reuses infrastructure cove already runs and keeps harness-agnosticism, at the price of gluing stages.
- **License differences matter little here but exist:** MIT (ai-git-bot, gh-aw) / MPL-2.0 (forgejo-mcp) / Apache-2.0 (PR-Agent) vs FSL + paid daemon (DevIntern).
- **Suitability classification needs repo context to be honest:** every source warns against speculative labels/PRs; the needs-info loop must survive in whatever cove builds, or triage produces confidently wrong candidates.

## Gaps

- No source documents a *Forgejo Actions-native* scheduled agentic triage (gh-aw is the only spec'd example, GitHub-only). A Forgejo Actions cron + forgejo-mcp + agent is uncharted but mechanically adjacent.
- Whether ai-git-bot's webhook/Gitea provider accepts Forgejo 15.0.3 (gitea-1.22 API) is unverified — same probe needed as the pullfrog analysis.
- Nothing surveyed implements the *full* three-stage pipeline on Forgejo with a bb/OpenCode harness — the combination appears to be genuinely unoccupied territory; the nearest neighbors are ai-git-bot (full pipeline, own harness) and the compositional path.