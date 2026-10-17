---
type: verification
timestamp: 2026-10-17T13:53:00Z
responding-to: runtime preservation documentation intent
---

## Operator docs and plan match the preservation contract

Per operator request: the Unreleased changelog and Forgejo service documentation now explain that extraction refreshes bundled source and pins while leaving `.env` and generated `nginx/default.conf` in place with stable inode identity until `cove up` rerenders nginx. The plan records the safe `.version` marker behavior, no-follow/nonblocking checks, the narrow allowlist, the temp-root regressions, and the separately deferred blank-root preflight. The tech-debt incident remains open and references draft PR #66. No live configuration was edited; the required gate is still waiting for recovery to finish.
