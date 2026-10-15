# Plan: Forge-side issue triage with master-ADE dispatch

**Status:** Scoped — probe (P0) blocks everything downstream
**Musing:** `docs/musings/2026-10-14-issue-triage-agents.md` (Decision of record, fork resolved 2026-10-14)
**Research:** trove `issue-triage-agents@f331955` (`docs/troves/issue-triage-agents/`)
**Related:** `docs/plans/forge-steward.md` (Tidesman — this triage workflow set is the steward's future second hosted workflow)
**Parley decisions (2026-10-14):** forge runner does triage only; code
implementation dispatches to the master ADE server (bb). Nothing else runs on
the runner. **Second directive:** the line does not stop at PR — it delivers
into the dev/nightly channels. Prod is fenced: hotpatch candidates escalate to
human review. Safety comes from picking fruit agents are good at, robust
testing, and automated UAT.

---

## Goal

A continuous pipeline that roombas the Forgejo issues list with no operator
in the loop: every issue gets scanned and classified on arrival, the backlog
is re-swept nightly, suitable issues are implemented by worker threads on the
master ADE server, and the results land back on the forge as PRs. The
operator's only steady-state touchpoints are read-only dashboards and the PRs
themselves. This is machinery, not a bot interface: no mention surfaces, no
comment chats. Comments and labels on an issue are machine-written records,
the line's audit trail.

Pipeline shape:

```
issue event (or nightly schedule)
  → Forgejo Actions workflow (triage, sealed runner)
      reads issue via /api/v1
      classifies via litellm.cove.local/v1 (gh-aw prompt pattern)
      bounded writes: allowlisted labels + max one record comment
      Suitable + blast-radius low? → label `agent-ready`
  → master ADE watcher (polls /api/v1 for `agent-ready`)
      swap label to `agent-dispatched`
      open bb thread on the repo checkout
  → bb/OpenCode implements, self-reviews, opens PR referencing the issue
  → delivery line
      CI green + review verdict clean + blast-radius low → auto-merge
      deploy to dev channel via the project's two-stage pipeline scripts
      automated smoke + UAT against dev
      nightly promotion after dev soak
  → prod: untouched. Genuinely prod-urgent fixes become hotpatch work orders
      under human review (apply the PR, or request an AI-drafted one)
```

Everything from intake to nightly promotion is machine-run. A human appears
only to review escalated hotpatch work and to live with the nightly result.

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

## Line design (industrial requirements, parley lens #2)

This is a production line, so the plan carries the machinery obligations the
surveyed tools each solved partially:

- **Issue state machine (the label set is the queue).** `untriaged` →
  classification labels → `agent-ready` (work order released) →
  `agent-dispatched` (thread opened) → `agent-merged` (PR merged) →
  `delivered-dev` (deployed + smoke/UAT green) → terminal `delivered-nightly`
  (promoted), `agent-bounced` (worker or delivery failed, reason recorded), or
  `needs-human` (gate refused, non-retryable, or prod-hotpatch escalation).
  Labels transition in one direction; no state is ever inferred, only read.
  Re-scans skip anything already in the machine.
- **Deployment-safety selection (the blast-radius gate).** Triage classifies
  each candidate `route: pipeline` or `route: needs-human` alongside
  suitability, so the line only ever swallows fruit agents are good at:
  small, self-contained, reversible changes in well-tested areas. Automatic
  escalations to `needs-human`: schema migrations, auth/crypto surface,
  deployment or infra config, dependency bumps with transitive reach,
  anything touching a live-data path, and anything the completeness or
  suitability gate cannot confidently clear. Selection quality is a primary
  safety mechanism, per the parley directive.
- **Idempotency.** The watcher dispatches an issue exactly once: the
  `agent-ready` → `agent-dispatched` swap happens before the bb thread is
  opened, so a crash between the two cannot double-dispatch. A re-dispatch
  only occurs via an explicit `agent-retry` label, never by label polling.
- **Backpressure.** Worker capacity is bounded: at most N concurrent bb
  threads on the master ADE (one per issue, cap set to the bb concurrency
  limit). The nightly scan releases at most one `agent-ready` per sweep per
  repo beyond what the pool can drain, so the queue lives in the label state,
  not in memory. Nothing in the pipeline needs to be fast; it needs to be
  steady and resumable after any crash.
- **Rework loop (DevIntern port, now mandatory).** A bounced thread or a
  failed delivery writes its failure reason as a machine-authored issue
  comment and applies `agent-bounced` (reasons: `implementation`,
  `delivery-failed`, `uat-failed`). The nightly sweeper may re-release a
  bounced issue to `agent-ready` at most `max-retries` times (default 2),
  then parks it `needs-human`. Bounce reasons feed the sweeper's scoring so
  the same trap does not recycle forever.
- **Prod escalation (the fence).** Prod is never automated. A issue judged
  prod-urgent (p0 with a running-instance incident behind it) parks at
  `needs-human` with a written record naming the recommended hotpatch path.
  The operator may apply the PR directly, or hand the work order back marked
  `agent-ready` + `hotpatch`, in which case the line drafts the hotpatch PR
  but human review gates the merge absolutely. Escalation is a label plus a
  record, not a conversation.
- **QA stage before humans.** Every worker thread runs its own review pass
  (bb auto-review) against its PR before completion; the PR carries the review
  summary as a machine record. Automated forge-side checks (CI status) gate
  merge candidacy. The first human eyes see a self-reviewed PR, not a raw
  attempt.
- **Delivery stage (merge → dev → nightly).** For `route: pipeline` work, the
  line controller merges when required checks are green, the auto-review
  verdict is clean, and the blast-radius class is low. Post-merge it deploys
  to the dev channel using the project's two-stage pipeline scripts
  (`scripts/staging/` deploy), runs automated smoke plus whatever UAT the
  repo declares (YAML-test-state-machine style suites runnable headlessly),
  and records the result. Delivery failure triggers the pipeline's rollback
  and records a `delivery-failed` bounce; nightly promotion (scheduled) runs
  off the dev channel after a successful soak. The deploy script pair
  (deploy + rollback/E2E/teardown) is a hard prerequisite; a repo without it
  routes `needs-human` by definition.
- **Observability.** Counters for the whole line, matching the ai-git-bot
  metric pattern: `issues_scanned`, `issues_classified{type,priority,route}`,
  `issues_dispatched`, `issues_bounced{reason}`, `issues_merged`,
  `delivery_deploys{channel}`, `delivery_rollbacks{reason}`,
  `delivery_uat{result}`, `issues_escalated{class}`, `watcher_polls`,
  `watcher_errors`. MVP exports from the watcher to the existing cove
  Prometheus; the Actions side is read from run logs until a metrics endpoint
  exists.
- **Operator surface: zero interaction, dashboards only.** Nothing in the
  pipeline waits for a reply. Machine-merge governs the dev/nightly path;
  humans hold prod merge authority and work the `needs-human` exception queue
  at their own pace.

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
- **Suitability + route** — `agent-ready` only when requirements and success
  criteria are clear and the scope is self-contained; the same verdict also
  emits `route: pipeline` or `route: needs-human` per the blast-radius gate
  (Line design). This gate is load-bearing: it exists because every surveyed
  tool that skips it produces confidently wrong PRs.
- **Write gate (fail closed)** — the workflow script (not the LLM) validates
  every proposed write: labels must match the allowlist set
  (`bug`, `feature`, `question`, `needs-info`, `p0`, `p1`, `p2`, `duplicate`,
  `invalid`, `spam`, `agent-ready`), at most 4 labels per issue, at most one
  comment, and the report comment is one fixed-template markdown table. The
  state-machine labels (`agent-dispatched`, `agent-merged`, `delivered-dev`,
  `delivered-nightly`, `agent-bounced`, `needs-human`, `hotpatch`, and any
  retries) belong to the line controller on the ADE server, which holds its
  own equally bounded write authority; the runner never writes them.
- **Report comment as record, not conversation.** The one comment the triage
  pass may write is a machine-templated record (type, priority, duplicate
  refs, suitability verdict), for audit and for later LLM context. Nothing
  reads replies to it as input.
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
| Master ADE watcher | ADE server; bb automation (cron script) polling `/api/v1/issues/search` | token with issue read + label write; enforces the label state machine (idempotent dispatch swap, retry caps, backpressure cap) |
| bb implementation thread | ADE server, bb CLI/env pointed at the repo checkout | issue number goes in the prompt; agent opens PR via `git.cove.local` remote; auto-review pass before handoff |
| Delivery controller | line controller on the ADE server (same watcher process, next job) | merge gate + calls the project's `scripts/staging/` deploy/rollback/E2E scripts against the dev channel; nightly promotion on schedule |
| Dev/nightly channels | per-project two-stage pipeline (`scripts/staging/`) | hard prerequisite for `route: pipeline`; missing pipeline forces `needs-human` |
| Automated UAT | repo test suites, YAML state-machine suites runnable headlessly | run post-deploy against dev; result recorded on the issue and counted in metrics |
| Metrics | ADE watcher → cove Prometheus | the `issues_*` / `delivery_*` / `watcher_*` counters listed under Line design |
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
- **P3 — ADE watcher (the line controller).** Poll script + bb thread opening;
  unit tests for the label state machine: idempotent dispatch on re-poll,
  retry cap after two bounces, park at `needs-human`, backpressure cap
  respected. First manual, then run unattended for a day before P4.
- **P4 — end-to-end seeded run.** Seed a fresh mix of issues covering both
  route classes (clean candidate, migration, dependency bump, auth touch,
  incomplete, spam, duplicate, p1 bug, prod-urgent p0), let the line drain
  them with no operator input, then inspect records after the fact: labels,
  report-record comments, bounced reasons, PRs, deploys, UAT results,
  metrics, and correct escalations at `needs-human`. The first
  run is supervised only because it is the first; the pass criterion is an
  unsupervised steady state over the seeded batch.
- **P5 — delivery wiring (per repo).** Verify the two-stage pipeline exists
  (deploy, rollback, E2E, teardown under `scripts/staging/`); wire the merge
  gate (required checks + review verdict + blast radius), the dev deploy and
  automated UAT run, and the scheduled nightly promotion with a dev soak
  window. Test the rollback path deliberately (inject a delivery failure)
  before trusting it. Repos without the pipeline route `needs-human` until
  they qualify.
- **P6 — rollout + steward fold-in.** Template the workflow for other repos;
  document the watcher in `docs/services/`; note that this workflow set is the
  forge-steward's future second hosted workflow (its triage moves from
  Actions-orchestrated to steward-hosted when Tidesman lands; the label
  contract survives unchanged, which is the whole point of deciding it now).

## Non-goals

- No coding agent on the runner, ever (parley decision, separation of duties).
- No human-interface surface: no mention triggers, no chat-in-comments, no
  conversational bots. Comments are machine records; the line does not read
  or await replies.
- No prod deployment, ever. The line's delivery ceiling is dev and nightly.
  Merge into prod-facing targets is human authority, exercised through the
  `needs-human` escalation queue; `hotpatch` work orders produce PRs for
  human review but are never machine-merged.
- No unbounded machine merge. Machine-merge applies only where required CI
  checks are green, the auto-review verdict is clean, and the blast-radius
  class is low; anything else parks for a human.
- No forge-side PR review service (approve/request-changes bots); that is
  Tidesman's charter (forge-steward plan).
- No AgentConnect / ai-git-bot / DevIntern adoption; behavior specs only.
- No GitHub side yet; gh-aw remains usable as-is for true GitHub repos, this
  plan is the Forgejo twin.

## Test command

Automated tests for the gate script land in the pilot repo (P1); declare the
command in that repo's AGENTS.md when it is created. The cove plan itself
carries no executable code, so no test command is declared here.