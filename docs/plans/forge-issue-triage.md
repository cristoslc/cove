# Plan: Forge issue line (event-oriented)

**Status:** Skeleton — Phase 0 blocks all
**Musing:** `docs/musings/2026-10-14-issue-triage-agents.md` (Decision of record)
**Research:** trove `issue-triage-agents@f331955` (`docs/troves/issue-triage-agents/`)
**Related:** `docs/plans/forge-steward.md` (Tidesman; this line later folds in as a hosted workflow)
**Review:** independently cross-checked by two surveyors (Claude Code Sonnet 5.5 and Codex gpt-5.6-terra, 2026-10-15); their critiques drove the queue redesign, the implementer sandbox, and the diff-time gates below.

## The one rule

Nothing awaits anything. Every component reacts to events and leaves its work where the next event can find it. Forge events (issue opened, label applied, PR opened, CI status), schedule ticks, and lease expirations are the only clock. No step calls a follower and waits for a result.

## Model

- Events arrive from three sources: the forge (issue and PR activity), the schedule (a nightly sweep), and timeouts (lease expiry on stuck work).
- Each component does one pass: observe, act, record, return. Blocking on a downstream component is forbidden; the event stream carries the result back instead.
- State lives in exactly one place: a local SQLite store on the ADE server, one row per `(repo, issue, revision)` with a lease, attempt count, and an outbox for forge writes. Forge labels and comments are projections for humans, written through the outbox. The store is the only authority; a fork of concern between them always resolves toward the store.
- A bb implementation thread is fire-and-forget. The watcher opens it in a worktree and moves on. Completion arrives as a forge event (the agent opens a PR referencing the issue) or as lease expiry (the reaper returns the row to the queue). Failure and latency are the same event: a timeout, not an error message.

## Phases

### Phase 0 — Probe (blocks everything)

One workflow on a scratch forge repo; save results as a recorded checklist.

- `on.issues` with its full type list (especially `labeled`), `on.schedule`, `on.issue_comment` on the default branch
- whether events authored by a bot token chain workflows (decides the whole dispatch choreography)
- whether `workflow_run` and branch-protection file patterns exist on 15.0.3
- runner version (`FORGEJO_*` context variables need Forgejo Runner 7.0.0+), plus a capture of real event payloads

Exit: checklist green, payloads saved.

### Phase 1 — Triage

A reactive triage workflow: `issues` event plus the nightly sweep. Read-only gather over `/api/v1`, classification through `litellm.cove.local/v1` using the gh-aw prompt pattern (completeness gate, spam gate, type, priority, duplicate-vs-related, suitability), allowlisted labels plus at most one record comment per issue. No dispatch, no merge.

Exit: on a hand-labeled sample of 20 to 50 real issues, classification precision is acceptable, and label/comment behavior is exactly-once.

### Phase 2 — Dispatch to PR

A watcher automation (bb automation on the ADE server) ingests forge events, claims work by lease in SQLite, fires a bb thread in a worktree, and moves on. The PR arrives later as a forge event; no merging in this phase.

- Implementer sandbox: branch-only forge token (no merge, no admin), a network allowlist of LiteLLM plus the forge only, no host credentials inside the worktree, a wall-clock and token budget per thread.
- Lease reaper: a test must force expiry and prove zero double-dispatch.

Exit: issues flow to PRs unattended; the forced-expiry test passes.

### Phase 3 — Merge and deliver, per qualifying repo (later, opt-in)

An event chain per PR: CI green observed, deterministic diff-path rules applied on the PR diff (the issue-time blast-radius read was a routing hint only), auto-escalation to human when the diff touches CI definitions, tests, or gate config, then gated merge, two-stage pipeline deploy to dev, automated UAT, and nightly promotion. Machine merge requires an attestation bundle keyed to the exact tested head SHA.

Eligibility: only repos whose two-stage pipeline exists (`scripts/staging/` deploy, rollback, E2E, teardown). A repo without it is never eligible until it qualifies.

Exit: one repo drains end to end unattended.

## Invariants (every phase)

- SQLite is the single authority; forge labels and comments are outbox-written projections.
- Untrusted input (issue text, PR diffs, linked content) never widens write scope. Writes are allowlisted and deterministic; the model cannot choose its own target repo, base branch, or escalation path.
- LiteLLM keys and any secrets stay out of every workflow file an agent PR can modify before merge.
- Bot-authored events run through a loop guard: skip events whose actor is the bot account.
- The nightly scan is idempotent (Forgejo skips DST-forward schedules, double-fires DST-backward ones, runs schedules only from the default branch, and has no catch-up).
- Watchers report liveness (`watcher_last_poll_age_seconds`) with an alert.

## Cut from earlier revisions (recoverable when a phase demands it)

Seven-state label machine and bounce sub-reasons (four labels plus SQLite rows cover it). The full Prometheus counter set (the store is the record; one liveness gauge in Phase 2). Triage-report tables (one fixed record comment). Operator-assisted UAT staging (the hand-labeled sample replaces it in Phase 1).

## Non-goals (standing)

Prod deployment. Machine merge on risky diffs. A coding agent on the runner. Reading comment replies as input. A forge-side PR review service (Tidesman's charter). The GitHub side (gh-aw stays the reference there).

## Test command

Executable tests begin in Phase 1 (gate script unit tests in the pilot repo's suite; declare the command in that repo's AGENTS.md). This plan carries no code, so no test command here.