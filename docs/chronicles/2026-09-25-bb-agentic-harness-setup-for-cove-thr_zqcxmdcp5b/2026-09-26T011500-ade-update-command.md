---
type: implementation
timestamp: 2026-09-26T011500
responding-to: operator approval of PR #57 + the question "how do we keep bb up to date within cove, then?"
---

## v0.8.0 promoted; bb update story answered with `cove ade update` (PR #58)

**Promote.** #57 squash-merged (`a6e3f63`), gate 621/28, tagged `v0.8.0`,
wheel built, stable tool reinstalled, verified (0.8.0; default compose set
includes ade).

**The update question.** The server container pins bb-app at image-build
time, so "keeping bb current" was previously a hand-rolled dance: edit pins in
three files, rebuild, hope. The design answer fell out of what the
investigation for Phase 2 had already established: **the server is the bb
version anchor** — it serves its own tarball to enrolled machines and daemons
self-update to its protocol (never downgrade). So updating the cove server IS
updating the harness, and the mechanism is `cove ade update`:

- target = npm latest (registry JSON — no npm CLI needed on the host) or
  explicit `--version`; `--check` is read-only,
- the pin + image tag land in the compose `.env` — the supported override
  surface, deliberately not re-synced by bringup, so it persists across
  `cove up`; image prefix preserved (staging),
- rebuild + recreate (data volume untouched), health through nginx,
  **auto-rollback** on failed health (version-tagged images make the old
  image a standing rollback path),
- `cove ade status` now prints the running version and warns on `.env`-pin
  drift, so the override never silently diverges from the wheel default —
  which pin-bump PRs realign for fresh machines.

**Pinned, never floating** — same posture as litellm/speedtest: no `latest`
tracking; explicit, versioned, rollback-able. Gate 629/28; PR #58 open (WIP).

**Enrollment tie-in:** with this, the Phase 2 sequencing on the operator's
machine becomes: merge #58 → promote 0.9.0 → `cove ade update` to align the
server with the installed host bb → run the cutover runbook → machines follow
the server forever after.
