---
type: implementation
timestamp: 2026-09-26T001500
responding-to: operator — "works now, but ade should come up by default, not require a second command. also, how do I register my local computer as a machine to cove?"
---

## ADE default-on (PR #57) + the Phase 2 enrollment answer

**Default-on.** The operator inverted Phase 1's opt-in posture — correctly,
per ADR-018's own words. The `ade` service loses its compose profile: every
`cove up` starts it, `cove status` treats a stopped ADE as a core failure,
`cove ade down` lasts only until the next `cove up`. Found while editing:
`cove up` reconciles *running* optionals via `COMPOSE_PROFILES`, so the
profile key was the only thing keeping the ADE out of the default set.
Pin bumped 0.43.4 → 0.44.0 (matches the operator's installed bb; bb machines
install the server's own tarball and daemons never downgrade, so server-side
staleness would poison enrollment).

**Machine registration — what the investigation established.** `bb machine
list` on the host shows `MBPBK-202602 … role: server`: the Mac runs its own
bb server holding every thread. bb's model is one server, many machines and
one daemon serves one server — so "register the Mac as a machine of the cove
ADE server" is necessarily a **cutover** (Phase 2), not an add-on. The cove
container server started tonight with a *fresh* DB (`~/Documents/cove-data/
ade/bb.db`, 22:59), so continuity requires migrating `~/.bb` into the volume
while both servers are stopped. The runbook (with honest caveats — Q1
enrollment is not yet live-verified) landed in `docs/services/ade.md`
(Machines). Enrollment deliberately stays a manual operator step: quitting bb
kills every session running under it, including any agent driving the
migration — the final switchover can never be safely autonomous.
