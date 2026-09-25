# Retro: ADE Phase 1 sashay (bb-server profile + ade.cove ingress)

**Date:** 2026-09-25
**Branch:** `bb/agentic-harness-setup-for-cove-thr_zqcxmdcp5b`
**PR:** #55 (squash-merged as `dfddf03`)
**Plan bookends:** `docs/plans/ade-harness-phase1.md` authored on branch at `c8aeaed`, never modified; trunk pre-state `bdf440f` (plan absent), trunk post-state `dfddf03` (plan + implementation). **Zero plan drift.**
**ADR:** ADR-018 (Accepted). **Chronicle:** `docs/chronicles/2026-09-25-bb-agentic-harness-setup-for-cove-thr_zqcxmdcp5b/` (11 entries, PR-comment interleaved).

## What happened

Phase 1 of ADR-018: bb server as a profiled Cove service (`cove-ade-server`, pinned `bb-app@0.43.4`), `ade.cove` nginx ingress with WebSocket support and a private-range allow-list, `cove ade up|down|status|logs` CLI, and an isolated staging E2E (`cove-staging` compose project on 127.0.0.1:9443). Three spikes gated the design (non-loopback bind, WebSocket/auth behind nginx, image build) and all passed. Two review rounds produced 11 findings, all fixed; an independent agent re-verified the fix delta. Gate finished at 608 passed / 28 deselected; staging E2E 3 passed live. The operator's live bb instance was never touched.

## What worked

- **Spike-before-design.** The three spikes were run before any implementation, and spike 2's finding (direct-URL bb carries no auth and permits exec/file reads) reshaped the ingress design honestly instead of being discovered post-merge.
- **The non-negotiable boundary as a review criterion.** "Must not disturb the live bb" was stated in the plan and then checked by both reviewers — it caught the staging design that would have re-rendered live nginx, and drove the isolated `cove-staging` project, which is a strictly better staging story for every future sashay.
- **Two-round review with an independent delta re-review.** Round 2 caught a real correctness bug (nginx reading an undefined `ade_port` Ansible var) that the fix-claim had papered over, plus an overclaim in the chronicle itself. Claims were audited, not trusted.
- **fj fallback path.** `fj pr create` failed (instance mismatch, then 403); the Forgejo API fallback worked immediately and became the standard for the rest of the sashay.

## What didn't

- **The `ADE_PORT` single-source-of-truth claim was wrong once.** The fix thread asserted the knob was threaded; the delta review proved the live nginx path read an undefined var. Cost: one extra round. Lesson applied: config-threading claims need a rendered-config test, not a grep test (now exists).
- **Review-response chronicle overstated a fix.** The entry claimed a coverage-matrix row was downgraded when the diff showed it unchanged. Corrected on the record in the next entry. Lesson: chronicle entries about test/coverage changes should cite the diff, not memory.
- **`fj` host-naming friction.** Keys are stored per-host and the working host key was `git.cove`, not `git.cove.local`; cost a few failed invocations before the token path settled.

## What surfaced

- **bb direct-URL mode is unauthenticated and permits command execution and file reads.** This is now a load-bearing fact in `docs/services/ade.md` and ADR-018: ingress enforces private-range allow + public deny, with ingress auth as the planned next control. Any future `*.cove` exposure of an agent-execution surface inherits this analysis.
- **Compose `-p` does not prefix explicit `container_name` values.** Verified with a synthetic merge before writing the override; every staging container gets an explicit `cove-staging-*` name. This is now pinned by tier-0 isolation tests.
- **`cove-staging` is reusable infrastructure**, not ADE-specific — future sashays can run E2E against branch state without touching the live stack.
- **Provider CLIs in containers (volume-persisted logins) remain unproven** — Phase 3 gate, tracked in ADR-018 open questions.

## Next actions

- Phase 2 (cutover of the live bb server into the container; host re-enrollment) — intent-and-wait, per ADR-018.
- Phase 3 (`cove ade up` machine containers; per-provider subscriptions-vs-API-keys decision) — gated on the container-auth spike.
- Ingress auth at nginx — planned control, recorded in `docs/services/ade.md` and ADR-018.
- Image-build coverage row is `manual` until a gated build test exists — `docs/test-coverage-matrix.yaml`.
- Remote branch deletion was not performed (enumerated irreversible action; operator authorization pending). The bb-managed worktree is this session's environment and is left to bb's lifecycle.
