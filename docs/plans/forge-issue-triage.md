# Plan: Forge-side issue triage with master-ADE dispatch

**Status:** Scoped — probe (P0) blocks everything downstream
**Musing:** `docs/musings/2026-10-14-issue-triage-agents.md` (Decision of record, fork resolved 2026-10-14)
**Research:** trove `issue-triage-agents@f331955` (`docs/troves/issue-triage-agents/`)
**Related:** `docs/plans/forge-steward.md` (Tidesman — this triage workflow set is the steward's future second hosted workflow)
**Parley decision (2026-10-14):** forge runner does triage only; code implementation dispatches to the master ADE server (bb). Nothing else runs on the runner.

---

## Goal

Issues at `git.cove.local` get automatically scanned, classified, and evaluated
for coding-agent suitability. Suitable issues flow to the master ADE server,
where bb opens implementation threads against the repository checkout. The
whole pipeline is offline-first: Forgejo Actions runner, `litellm.cove.local`,
and the ADE server all sit on the cove network.

Pipeline shape:

```
issue event (or daily schedule)
  → Forgejo Actions workflow (triage, sealed runner)
      reads issue via /api/v1
      classifies via litellm.cove.local/v1 (gh-aw prompt pattern)
      bounded writes: allowlisted labels + max one comment
      Suitable? → label `agent-ready`
  → master ADE watcher (polls /api/v1 for `agent-ready`)
      swap label to `agent-dispatched`
      open bb thread on the repo checkout
  → bb/OpenCode implements, opens PR referencing the issue
```

## Architecture choices (decided in parley)

1. **Trigger surface: Forgejo Actions, not webhooks, not ai-git-bot.** The
   Forgejo Actions reference documents `on.issues` (types opened, reopened,
   labeled, edited, …) and `on.schedule`. That matches the gh-aw `issue-triage`
   pattern (event-driven) plus the Issue Monster pattern (scheduled backlog
   scan) directly. Path A (ai-git-bot) collapsed: its turnkey value was the
   bundle, and the bundle's parts already exist in cove.
2. **The runner stays sealed.** The triage job holds a forge token with
   issue/label scopes only, calls LiteLLM, and performs writes exclusively
   through a fixed gate script. It must never hold bb credentials, never check
   out more than read-only issue data, and never execute LLM-proposed shell.
   Prompt injection from an issue body can, at worst, produce a wrong label
   from the allowlist or one wrong comment — nothing more.
3. **Dispatch contract is a label, mirroring AgentConnect.** `agent-ready` =
   "triage judged this a Suitable coding-agent candidate." The ADE watcher
   swaps it to `agent-dispatched` when it opens the bb thread. The audit trail
   lives in the issue itself; no new orchestration surface between stages.
4. **Watcher polls, webhooks rejected for MVP.** A cron/bb-automation poll of
   `/api/v1` (label filter, e.g. every 5 min) needs no inbound endpoint on the
   ADE server. A webhook receiver is a later optimization; latency is not the
   requirement, correctness is.

## Triage contract (ported from gh-aw, tightened)

One triage run per issue, structured output validated by a fixed script:

- **Gather** — issue, comments, existing labels, repo docs/index, search for
  duplicates and related issues (read-only REST).
- **Completeness gate** — missing info → `needs-info` label + at most one
  comment with specific questions. Never guess type, priority, or solution.
- **Spam/invalid short-circuit** — `spam` or `invalid`, one comment, done.
- **Classification** — exactly one type, one priority (p0 security/data-loss/
  outage → p1 major regression without workaround → p2 normal actionable).
- **Duplicate-vs-related** — apply `duplicate` only on high confidence with a
  cited issue number, never on title similarity; list at most 3 matches in the
  report comment.
- **Suitability** — `agent-ready` only when requirements and success criteria
  are clear and the scope is self-contained; otherwise `needs-info` or a
  plain report. This gate is load-bearing: it exists because every surveyed
  tool that skips it produces confidently wrong PRs.
- **Write gate (fail closed)** — the workflow script (not the LLM) validates
  every proposed write: labels must match the allowlist set
  (`bug`, `feature`, `question`, `needs-info`, `p0`, `p1`, `p2`, `duplicate`,
  `invalid`, `spam`, `agent-ready`), at most 4 labels per issue, at most one
  comment, and the report comment is one fixed-template markdown table.
- **Backlog scan (schedule)** — daily cron run; scores open, untriaged issues;
  ensures candidates are distinct and non-overlapping before any `agent-ready`
  goes out (Issue Monster discipline); cheap model tier suffices (gh-aw audit
  said so too).

## Where each piece lives

| Piece | Location | Notes |
|---|---|---|
| Triage workflow YAML | Target repo `.forgejo/workflows/issue-triage.yml` | installed per pilot repo; later templated |
| Triage gate script | same repo `.forgejo/scripts/triage/` | validated-writes gate, unit-testable |
| LiteLLM endpoint | `litellm.cove.local/v1` (existing) | cheap model route for triage |
| Forge token | Forgejo Actions secret, per repo | scopes: issues:read, write limited to issue/label; never a repo-write token |
| Master ADE watcher | ADE server; bb automation (cron script) polling `/api/v1/issues/search` | token with issue read + label write, stored via the ADE secrets flow |
| bb implementation thread | ADE server, bb CLI/env pointed at the repo checkout | issue number goes in the prompt; agent opens PR via `git.cove.local` remote |
| Label set | created on pilot repo | contract labels above |

## Stages

- **P0 — probe (blocks all).** On a scratch Forgejo repo, install a workflow
  with `on: issues: [opened, reopened, labeled]` + `on: schedule` that logs
  `${{ forgejo.event_name }}` etc. and runs on the Actions runner. Confirms
  cove's Forgejo 15.0.3 accepts both events end to end. If absent, the plan
  falls back to a webhook listener (documented fallback of Path B), but the
  docs say it is present in v15.
- **P1 — triage gate script (TDD).** Unit-test the writer gate first: a
  failure-expecting test that a proposed out-of-allowlist label, a second
  comment, or 5 labels is rejected; then pass cases. No LLM involved in these
  tests. Tests live in the pilot repo's test suite; test command declared in
  that repo's AGENTS.md.
- **P2 — triage workflow wired.** YAML + secrets on the pilot repo; run
  against seeded issues (one per contract branch: incomplete, spam, duplicate,
  p1 bug, clean candidate). Verify exactly-once comment/label behavior.
- **P3 — ADE watcher.** Poll script + bb thread opening; unit tests for the
  label swap idempotency (must not double-dispatch on re-poll). First manual.
- **P4 — end-to-end UAT.** Operator-assisted: file a real issue, watch labels
  land, watch the bb thread open on the ADE server, review the PR it opens.
  Per test rules this is stage-gated on P0–P3 passing.
- **P5 — rollout + steward fold-in.** Template the workflow for other repos;
  document the watcher in `docs/services/`; note that this workflow set is the
  forge-steward's future second hosted workflow (its triage moves from
  Actions-orchestrated to steward-hosted when Tidesman lands; the label
  contract survives unchanged, which is the whole point of deciding it now).

## Non-goals

- No coding agent on the runner, ever (parley decision, separation of duties).
- No AgentConnect / ai-git-bot / DevIntern adoption; behavior specs only.
- No GitHub side yet; gh-aw remains usable as-is for true GitHub repos, this
  plan is the Forgejo twin.
- No automated PR review; that is Tidesman's charter (forge-steward plan).

## Test command

Automated tests for the gate script land in the pilot repo (P1); declare the
command in that repo's AGENTS.md when it is created. The cove plan itself
carries no executable code, so no test command is declared here.