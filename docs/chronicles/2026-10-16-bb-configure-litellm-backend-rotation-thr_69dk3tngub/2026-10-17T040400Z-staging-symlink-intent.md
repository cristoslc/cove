---
type: intent
timestamp: 2026-10-17T040400Z
responding-to: operator request to extend symlink fix to isolated staging
---

## Cover the isolated staging setup path

Per operator request: I will add a staging regression that pins `deploy-isolated.sh` to the no-follow helper and verifies that helper rejects a symlink target without changing its content or mode. Then I will replace staging's `touch` and `chmod` with the helper invocation. Success means all three setup paths share the safe file handling.
