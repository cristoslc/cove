# Musing: `cove update` and `cove update auto`

**Status:** Proposal (musing → ADR)
**Date:** 2026-09-26
**Revised same day** — first draft proposed "notify-only by default" for
scheduling. Operator correction: that recreates the busywork auto exists to
kill. The opt-in **is** the approval. This version is rewritten around that.

## Decision (2026-09-26, operator) — supersedes the tier design

> "cove is meant for convenience, not for enterprise controls. We're making a
> commitment with our vendor update policy. `cove update` should just mean
> "get the latest version of cove cli and then update all the
> containers/images/services/etc. to the version it specifies, with whatever
> migrations are necessary". `cove update auto` should just set up daily
> updates."

So the design collapses to the vendor-update model:

- **`cove update`** = update the cove CLI to the latest tagged release, then
  bring the whole stack to whatever that release specifies (pins, images,
  migrations — via the normal `cove up` flow, which Forgejo's own data
  migrations and Vault's unseal flow already ride). One command, one source
  of truth: the released cove version. No per-service decisions at update
  time.
- **`cove update auto`** = register a daily launchd job that runs it. Set up
  once; after that there is no operator in the loop.
- Per-service escape hatches (`cove ade update --version X`) remain for
  targeted pins and rollbacks, but they are escape hatches, not the model.

The first draft's tier ceremony (float/auto/manual per service, notify-only
scheduling) is **superseded** — it solved a governance problem the operator
has declined to have. What survives from the first draft: the staleness
audit below (it made the case), and the constraint that scheduled runs must
be non-interactive (see below).

### Scheduling constraint

A daily job cannot prompt for a BECOME password or a 1Password biometric.
`cove update` in quiet mode therefore rides the passwordless-sudo path
AGENTS.md already offers (`/etc/sudoers.d/cove` for the narrow bringup
sudoers set) and skips provisioning; the tasks that need elevation
(/etc/hosts, pf redirect) are idempotent and already `failed_when: false`, so
an established machine converges without a prompt. First-boot and any task
that genuinely fails still surface in `cove update log` — rollback events and
failures always notify; routine successes are silent by design.

---

## superseded first draft (kept for the record)

The original tier proposal — notify-only default, float/auto/manual per
service, manual Vault/Forgejo-major carve-outs — is superseded. Its honest
residue: the staleness audit below, and the principle that Forgejo major
bumps and Vault upgrades still get a scheduled operator session (they are
migrations, not updates).

## The commitment we already made (audit, 2026-09-26)

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

### The CLI's own updates

`cove update` **is** the CLI's own update — it installs the latest tagged
release first, then converges the stack to it. Never trunk (the sashay rule
stands); the wheel attached to a tagged release is the only artifact `update`
consumes.

## Open questions (parked, not blocking)

- Cadence: daily at a fixed hour vs on-wake. Default: daily.
- Whether staleness surfaces in `cove status` output.
- Post-Phase-2 fleets: the cove ADE server can push version intent to enrolled
  machines (bb already does exactly this for its own daemons) — revisit when
  machine #2 exists.

## Addendum (2026-10-13): convergence is gated, not unconditional

The first implementation always ran bring-up after the CLI phase — the
operator correction: `cove update` brings up only when (a) the release's
bundled compose actually differs from what is deployed (a real pin change),
and (b) there is a running stack to converge at all. `.env` overrides and the
gitignored runtime artifacts bringup generates locally (rendered nginx
config, dnsmasq config, credential seeds) never count as pending. A downed
stack stays down — updates converge running services, `cove up` remains the
explicit way to start the stack. The new wheel's bundled pins are read from
the wheel itself, because the process doing the comparison still runs the
old code until restart. Fail-soft default: if the bundled tree cannot be
read, convergence is assumed pending (converge rather than silently skip).

## Addendum (2026-10-21): the compared wheel is the installed wheel

Issue #80: the pin-compare crashed with FileNotFoundError because the wheel
path `_install_wheel` returned pointed into a TemporaryDirectory deleted the
moment the function returned — the build was fine, the path dangled. The
rule now: the pin-compare reads the exact wheel file `uv tool install`
consumed, and its temp tree is released by the update flow after the
comparison (a missing wheel is a fail-loud ClickException, never a raw
traceback). Two related corrections in the same fix: the temp-worktree build
now runs the tag's own `sync_compose_resources.py` before `uv build`
(`cli/cove/resources/compose/` is a gitignored build artifact, so a fresh
worktree previously produced a wheel with no bundled pins at all), and the
wheel is built outside the git worktree so worktree cleanup cannot take it.
Downloading the release asset instead of rebuilding at the tag remains the
design-pure path if a second machine ever makes asset plumbing worth it.
