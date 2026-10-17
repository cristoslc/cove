---
type: checkpoint
timestamp: 2026-10-17T044100Z
responding-to: required teardown hardening test gate
---

## Teardown regressions and repository gate pass

**Responding to:** the staging teardown fix and its test-first coverage.

Per operator request: the focused teardown regressions pass (2 passed), `bash -n scripts/staging/teardown.sh` passes, and the required gate passes (776 passed, 31 deselected, five `getpass` warnings). The tests now cover every profile declared in the base and staging Compose files, including LiteLLM, plus canonical root overlap through a `staging/../live` alias. No live or staging service was run.

See [scripts/staging/teardown.sh](https://git.cove.local/cristos/cove/src/branch/bb/configure-litellm-backend-rotation-thr_69dk3tngub/scripts/staging/teardown.sh) and [cli/tests/test_staging_isolation.py](https://git.cove.local/cristos/cove/src/branch/bb/configure-litellm-backend-rotation-thr_69dk3tngub/cli/tests/test_staging_isolation.py).

**Commits in this unit:** teardown fix and coverage commit immediately precedes this projection
