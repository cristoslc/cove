# Musing: `cove update` and `cove update auto`

**Status:** Proposal (musing → ADR)
**Date:** 2026-09-26
**Revised same day** — first draft proposed "notify-only by default" for
scheduling. Operator correction: that recreates the busywork auto exists to
kill. The opt-in **is** the approval. This version is rewritten around that.

## The commitment we already made

Pinning built-in services means Cove ships their updates. There is no
opting out of the maintenance — only deferring it, badly. The staleness
audit (2026-09-26) says we are already deferring it badly:

| Service | Cove pin | Upstream | Behind |
|---|---|---|---|
| Forgejo | `:15` (floating major) | **v16.0.5** (16.0.x since ~Jul, patched same-day with 15.0.9) | **one major** |
| LiteLLM | `cove-litellm:1.84.0` (custom build) | pypi 1.102.1 | ~18 minors |
| Speedtest | `v1.14.5-ls162` | `v1.15.0-ls173` | one minor, 11 ls-revisions |
| Vault | `1.20` **digest-pinned** | (digest pin = zero float) | manual-only by design |
| nginx | `1.27-alpine` (floats in major) | 1.27.5 stable | current |
| bb-app (ADE) | `0.44.0` wheel default | 0.44.0 | current, and now has `cove ade update` |

Forgejo at 15 isn't negligence — 15.0.9 still gets same-day security patches —
but it *is* a full major of accumulated migration debt waiting for whoever
finally does the bump by hand. LiteLLM at 1.84 vs 1.102 is worse: a custom
Docker build nobody re-cuts until something breaks. This is what "pinned"
means without a scheduler: **staleness with extra steps**.

## The control point is setup, not each update

First draft had `auto` defaulting to notify-only, on the theory that a human
should approve each update. Wrong: an auto mode that pings the operator is a
reminder system, not a maintenance system. The approval happens once — at
setup, per service, as a **tier choice** — and after that the schedule runs
without the operator in the loop. What the operator approves at setup is the
tier, and the tier encodes blast radius:

- **`float`** — re-pull the existing pin (forgejo `:15`, nginx `1.27-alpine`)
  on cadence: minors and patches land automatically, **majors notify and
  wait** (a major is a migration, and migrations deserve a scheduled operator
  session, not a Tuesday-morning surprise). Fixes the second gap this audit
  exposed: bringup pulls with `--pull missing`, so even our floating tags
  never actually refresh on an existing machine.
- **`auto`** — apply anything upstream ships, with pre-apply volume snapshot
  and automatic rollback on failed health. Admission criteria: the service
  already proves it can revert itself (ADE qualifies: version-tagged images,
  health-gated, auto-rollback — `cove ade update`'s whole design). Speedtest
  qualifies with a snapshot step. This tier is the default for anything
  Cove builds itself.
- **`manual`** — Vault (digest pin exists precisely because unseal and
  migration are ceremonies), Forgejo major bumps (data migrations, downtime
  window). The operator can *raise* a service into manual; they cannot
  silently fall out of their chosen tier.

`cove update auto` registers the launchd job at the chosen tiers and reports
what it did (`cove update log`, notifications on rollback — rollback is the
one event that always pages a human). `cove update --check` survives as the
read-only view, and `cove status` surfaces "N updates pending" — visibility
without decision fatigue.

## What the CLI update surface looks like

```
cove update --check                 # staleness report (all services + CLI)
cove update apply [--service S]     # one-shot apply within the configured tier
cove update auto --tier ade=auto,speedtest=auto,forgejo=float,vault=manual
cove update log                     # what auto did, when, and whether it rolled back
```

LiteLLM's custom build moves to a scheduled image re-cut (`auto` tier once
its build is health-gated the way ADE's is) — that is the fix for the 1.84 →
1.102 gap, not a manual PR per bump.

## The CLI's own updates

`cove update cli` reinstalls the stable tool from the latest **tagged**
release — never trunk (the sashay rule stands). Patch releases auto-apply
under `auto`; minor/major CLI releases notify, because a CLI bump can change
bringup behavior (v0.7.0's cert regression is the standing counterexample —
and note it was *caught* by the self-heal that shipped in its patch, which is
the argument that auto-apply with real rollback is safer than scheduled
manual bumps that pile up).

## Open questions (for the ADR discussion, not this musing)

- Cadence: daily at a fixed hour, on wake, or piggybacked on `cove up`?
- Snapshot mechanism per service (volume tar? compose-level?) and retention.
- Post-Phase-2 fleets: does the cove ADE server *push* version intent to
  enrolled machines (bb already does exactly this for its own daemons), or do
  machines check independently?
- Whether `cove update auto` should also drive the *repo-side* pin bumps
  ( Dependabot-style PRs so the wheel default never lags the .env override).
