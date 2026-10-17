---
type: checkpoint
timestamp: 2026-10-17T043726Z
responding-to: staging teardown regression test run
---

## Reproduce the profile and root-guard gaps

**Responding to:** the test-first coverage for staging teardown profile cleanup and data-root isolation.

Per operator request: the focused tests fail on two defects. Teardown does not enable Compose profiles `litellm`, `runner`, `speedtest`, or `tunnel`; the failure includes the reported LiteLLM service and database. A path containing `cove-data-staging/../cove-data` passes the string checks, then the script exits successfully after deleting the live-root sentinel in the isolated test fixture. I will update teardown to enable all profiles declared by Compose and reject canonical root overlap before Compose or file removal. No services were run.

See [scripts/staging/teardown.sh](https://git.cove.local/cristos/cove/src/branch/bb/configure-litellm-backend-rotation-thr_69dk3tngub/scripts/staging/teardown.sh), [compose/docker-compose.yml](https://git.cove.local/cristos/cove/src/branch/bb/configure-litellm-backend-rotation-thr_69dk3tngub/compose/docker-compose.yml), and [cli/tests/test_staging_isolation.py](https://git.cove.local/cristos/cove/src/branch/bb/configure-litellm-backend-rotation-thr_69dk3tngub/cli/tests/test_staging_isolation.py).

**Commits in this unit:** none yet
