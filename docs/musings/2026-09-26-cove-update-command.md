# Musing: `cove update` and `cove update auto`

**Date:** 2026-09-26
**Status:** Proposal (musing — no ADR yet)
**Trigger:** operator question after `cove ade update` shipped (#58): "do we need a new musing on a `cove update` and `cove update auto` (scheduled)?"

## The problem, stated plainly

Cove services are pinned, and each has its own update surface:

| Service | Update mechanism today |
|---|---|
| ADE (bb-app) | `cove ade update` (PR #58) — npm target → .env pin → rebuild → health → auto-rollback |
| LiteLLM / Headroom | pin in compose; update = repo PR + promote (wheel IS the deploy) |
| Speedtest Tracker | image pin in bringup; update = PR + promote |
| Forgejo / Vault / nginx / dnsproxy | image pins in compose; same |
| **cove CLI itself** | manual promote flow: gate → sync → build → `uv tool install --force` |

So today "update cove" means: know which of six things moved, write the right
PR, pass the gate, promote, reinstall, run `cove up`. Nothing is wrong with
any single step — but nothing tells the operator *what is stale*, and nothing
automates the safe parts. The question is whether a `cove update` surface and
a scheduled `cove update auto` should exist, and what they may touch.

## Tensions (why this needs thinking, not just code)

1. **Promote is deliberately manual.** AGENTS.md: stable tool reflects
   *released* state only; gate must be green; sashay-aware. Any `cove update
   auto` that reinstalls the CLI from trunk bypasses all of that. Hard
   constraint, not a preference.
2. **The failure mode is proven.** The cert-SAN regression (v0.7.0 → 0.7.1)
   shipped *because* the upgrade path of an existing deployment was never
   exercised. Unattended upgrades multiply the number of upgrade paths that
   must be pre-verified — and we cannot pre-verify what we don't gate.
3. **Pinned-never-floating is the posture.** litellm, forgejo, vault, bb-app:
   every pin exists so an update is an explicit, versioned, rollback-able
   event. `auto` must not quietly float anything.
4. **The bb precedent cuts both ways.** bb itself auto-updates *machines* to
   the server's protocol (`--auto-update`, never downgrade) — the harness's
   own model says: anchor the version in one place, let followers converge.
   Cove could mirror that: main is the anchor, `cove update` converges a
   machine to it. But cove's "client" is the operator's whole stack, not a
   disposable daemon.

## Proposal: three tiers, not two commands

**`cove update --check`** (always safe, schedulable) — a read-only staleness
report across every surface:

- CLI: installed version vs latest tagged release on git.cove
- services: running image tag vs repo pin vs upstream latest (ade via npm
  registry; forgejo/litellm/speedtest via their registries)
- output: what's stale, what command or PR updates it

**`cove update`** (explicit, per-surface) — applies what the operator names:

- `cove update ade [--version X]` → delegates to the existing
  `cove ade update` (already built)
- `cove update cli` → fetches the latest tagged release artifact from
  git.cove, verifies the tag, reinstalls the tool — the *release* action, not
  a trunk action, so the sashay rule holds (tagged releases only)
- litellm/speedtest/forgejo pins stay PR-gated (image digests, seed migrations,
  admin identity — these are not mechanical bumps)

**`cove update auto`** (scheduled, opt-in, conservative by default) — a
launchd job (macOS; systemd elsewhere) running on a cadence:

- default tier: **notify only** — run `--check`, push findings to ntfy (the
  notification-service musing already exists) and/or the bb host; never change
  anything unattended
- opt-in tier: `--apply-ade` — auto-run `cove ade update` when the only change
  is a bb-app patch/minor bump, because that path already has: version-tagged
  images, automatic rollback on failed health, and the server-anchors-machines
  model. bb-app is the one service whose update is already *self-healing* by
  construction; it is the right first auto-apply surface
- never: Forgejo/Vault (stateful, migration-bearing), never the CLI wheel
  itself, never on a metered/unstable link

The principle: **automate the check, automate the revertible, never automate
the gate.** `--check` + notify is the 80% win; auto-apply is a narrow,
explicitly-named carve-out for paths that already carry their own rollback.

## What this musing is NOT deciding

- Whether `cove update` belongs in the CLI vs a separate tool (CLI — it needs
  compose context, creds, and the state machine).
- ntfy vs bb notifications as the channel (separate musing).
- Repo-side automation (a CI check that opens a PR when an upstream pin lags —
  the Dependabot pattern, which this repo has history with). Noted as a
  follow-on, not part of the first cut.

## Recommendation

Yes — musing first, ADR later. Concretely:

1. Land `cove update --check` as the read-only staleness report (small, pure
   wins, rides the `cove ade update` pattern).
2. Add `cove update cli` (tagged-release-only reinstall) — but only after a
   staging test proves the tagged-wheel install path, given the SAN lesson.
3. Ship `cove update auto` in notify-only mode; `--apply-ade` gated behind an
   explicit flag and its own ADR-016-style adoption argument.

Open questions for the discussion: cadence (daily? on `cove up`? on wake?),
whether `--check` results should surface in `cove status`, and whether
multi-machine fleets (post-Phase-2) want the server to *push* version intent
to machines rather than each machine checking independently.
