---
title: "Issue triage → agent-ready candidates: the tooling landscape"
created: 2026-10-14
status: Exploring
trove: issue-triage-agents@f331955
---

# Issue triage → agent-ready candidates: the tooling landscape

Origin: the operator watching issues pile up faster than time and attention can
tackle them. The question: what tooling exists to **scan** forge issues,
**triage** them, and **identify candidates for automated implementation** with a
coding agent — offline-first, compatible with cove's Forgejo at
`git.cove.local`?

Full research lives in the trove `issue-triage-agents@f331955`; this musing is
the half-formed read of it.

## The shape of the answer

The pipeline is three stages — **scan → triage → implement** — and no surveyed
tool is best at all three. The landscape clusters:

1. **ai-git-bot** — the turnkey option, and the closest to the whole ask in one
   Docker container. MIT, self-hosted, Gitea production-ready (Forgejo = Gitea
   API, untested), local LLMs via Ollama/llama.cpp/OpenAI-compatible →
   `litellm.cove.local/v1`. It ships three issue workflows: **Issue Triage**
   (read issue → pick one assignee → post routing reason), **Writer Agent**
   (rough issue → background/requirements/acceptance criteria), **Coding Agent**
   (assigned issue → clone → implement → validate → open PR). Caveat: its
   triage is *routing* — "who owns this" — not "would an agent do this well."
2. **Compositional, harness-agnostic** — forgejo-mcp (Go MCP server, Forgejo
   first-class, docker `ronmi/forgejo-mcp`, stdio mode) + any MCP-speaking
   harness (bb/OpenCode) + a scheduled bb thread scanning the backlog. bb
   already runs on this machine; bb automations provides the cron. The triage
   brain is a prompt, and the best published prompt is GitHub's gh-aw
   `issue-triage` sample (read-only pass + safe-outputs pattern): completeness
   gate → spam gate → type/priority → duplicate-vs-related → **coding-agent
   suitability (Suitable / Needs more info / Needs maintainer judgment)** → one
   report comment.
3. **AgentConnect** — a real product in the forge-steward category the pullfrog
   musing decided to hand-build. Gitea support shipped 2026-09-13, but it
   requires Gitea 1.23+ and cove's Forgejo is 15.0.3 / gitea-1.22.0 base —
   below the stated floor. Its label-triggered dispatch ("adding a matching
   label can start the agent") is nonetheless the cleanest existing model of
   triage-label → agent-run composition, and it speaks ACP (any harness).
4. **Component-grade**: PR-Agent's `similar_issue` (CLI, one cheap LLM call) is
   a working duplicate-detection pass for the backlog — the only *shipped*
   version of the `similarIssues` feature the pullfrog musing dropped. DevIntern
   is the best *behavioral spec* for the worker stage (task_query polling, vague
   tickets get questions not wrong PRs, incomplete attempts bounce back with an
   explanation) but has no Forgejo tracker and an FSL/paid-daemon fine print.

## What I noticed

- **Assignment IS the dispatch contract.** ai-git-bot implements an issue when
  it's assigned to a bot with the Coding Agent workflow; AgentConnect starts an
  agent on a label. Either way the triage pass dispatches implementation with a
  plain forge write (assign/label) that stays auditable in the issue itself. No
  new orchestration surface required between stage 2 and stage 3.
- **The "Issue Monster" pattern** (gh-aw blog): a scheduled workflow that wakes
  up, scores open issues, checks candidates "distinct and not overlapping," and
  hands the best to the coding agent. Audit tooling flagged it for a cheaper
  model — triage doesn't need a frontier engine.
- **Suitability is the load-bearing output.** The honest gate from gh-aw: only
  mark *Suitable* when "requirements and success criteria are clear, and the
  scope is self-contained." Every surveyed tool that skips this gate produces
  confidently wrong PRs; DevIntern's "vague → questions, not a wrong PR" is the
  alternative encoding of the same idea.
- **Cove needs to build nothing for the scan.** Forgejo's `/api/v1` plus
  forgejo-mcp (or `tea`) already gives an agent the backlog; the missing piece
  is the *scheduled, gated, one-report-per-issue discipline* around it.

## Fork in the road (needs a parley)

- **Path A — deploy ai-git-bot** as a cove container against `git.cove.local`
  and see if its Gitea provider accepts Forgejo 15.0.3. Fastest to value; loses
  the harness-agnostic constraint (its coding agent is its own LLM loop, not
  bb/OpenCode); Forgejo support is unprobed.
- **Path B — compose** a scheduled triage thread on bb automations + forgejo-mcp
  (or the forge layer of the Decided forge-steward plan, once built) using the
  gh-aw prompt pattern with safe-outputs discipline (allowlisted labels, capped
  writes). Reuses everything cove runs; zero new architecture; more glue.
- **Path C — fold into the forge-steward plan.** The pullfrog musing is Decided
  and its next step is the forge-layer rewrite plan. Triage could be the second
  workflow that layer hosts (scan → suitability → label → the steward's coding
  agent), keeping one forge-facing service instead of two.

Path C composes with the decided plan; Path B is the hedge that works before
any steward exists. Worth a parley before anything becomes a plan — and per the
ritual, `musing → plan → sashay`, no implementation on trunk from here.