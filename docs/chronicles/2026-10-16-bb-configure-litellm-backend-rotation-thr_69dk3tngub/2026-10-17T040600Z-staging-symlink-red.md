---
type: result
timestamp: 2026-10-17T040600Z
responding-to: staging symlink regression intent
commit: 9603479
---

## Staging symlink regression is red

Per operator request: the new staging contract requires `deploy-isolated.sh` to invoke the no-follow helper before Compose starts, then executes that helper against a symlink and verifies the external target remains unchanged. The focused regression failed first at the missing helper invocation, confirming staging still used unsafe `touch`/`chmod`. The test is committed before updating the script.
