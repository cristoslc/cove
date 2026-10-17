---
type: intent
timestamp: 2026-10-17T043749Z
responding-to: staging teardown regressions pass
---

## Run the repository gate for teardown hardening

**Responding to:** both staging teardown regressions pass after enabling every declared Compose profile and adding canonical data-root overlap checks.

Per operator request: I will run Cove's required non-E2E/non-staging test gate and review the focused diff. Success means the repository gate passes, no live or staging services are invoked, and the changes are ready for an interleaved commit and receipt.

**Commits in this unit:** none yet
