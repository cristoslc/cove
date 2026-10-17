---
type: intent
timestamp: 2026-10-17T085703Z
responding-to: operator request to resume the authorized 0.14.0 release after PR #64 merged
---

## Resume the 0.14.0 release

**Responding to:** the operator authorized resuming the 0.14.0 release on main after the staging teardown test fix merged as PR #64.

Per operator request: fetch `origin`, fast-forward clean `main` to `3c54430`, restore the named release-edit stash, and verify its contents before running the fresh gate and release steps. Success means the merged main tree and only the intended release metadata edits are present, with no live configuration touched.

**Commits in this unit:** none yet
