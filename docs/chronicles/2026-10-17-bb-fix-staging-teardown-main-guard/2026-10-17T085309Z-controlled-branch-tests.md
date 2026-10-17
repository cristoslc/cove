---
type: checkpoint
timestamp: 2026-10-17T085309Z
responding-to: the required gate failure where teardown's main guard masked the overlap assertion
---

## Control the branch context in teardown tests

**Responding to:** the required gate failure on `main`, where `teardown.sh` correctly refused its current checkout before the overlap guard ran.

Per operator request: the overlap test now copies the teardown script into a temporary Git repository on an explicit `review-branch`; a separate test runs the same safety guard from an isolated `main` branch and checks that the live-root sentinel remains unchanged. The focused tests pass (2 passed), with no change to `teardown.sh` and no service invocation.

See [cli/tests/test_staging_isolation.py](https://git.cove/cristos/cove/src/branch/bb/fix-staging-teardown-main-guard/cli/tests/test_staging_isolation.py).

**Commits in this unit:** none yet
