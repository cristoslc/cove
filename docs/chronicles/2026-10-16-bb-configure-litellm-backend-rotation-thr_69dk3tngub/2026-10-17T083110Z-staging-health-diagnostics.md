---
type: checkpoint
timestamp: 2026-10-17T083110Z
responding-to: isolated staging deploy health gate
---

## Isolated staging health diagnostics

**Responding to:** The branch wheel check passed and the isolated staging deploy started project `cove-staging` from PR #63.

The deploy script brought up seven containers under the staging Compose project. ADE became healthy. Vault became unhealthy, and ToolHive repeatedly restarted; its logs report that no container runtime is available even though `/var/run/docker.sock` is mounted read-only. Docker uses the `orbstack` context on this host. I stopped the deploy command during its health wait after recording those diagnostics. No live project container was targeted.

The stock E2E script will now run against `https://127.0.0.1:9443` to capture its useful coverage and any related failures. The LiteLLM overlay smoke remains the primary check; staging will be removed afterward using the default staging root.

See [`scripts/staging/deploy-isolated.sh`](https://git.cove/cristos/cove/src/branch/bb/configure-litellm-backend-rotation-thr_69dk3tngub/scripts/staging/deploy-isolated.sh) and [`scripts/staging/e2e.sh`](https://git.cove/cristos/cove/src/branch/bb/configure-litellm-backend-rotation-thr_69dk3tngub/scripts/staging/e2e.sh) for the invoked entry points.

**Commits in this unit:** 1754927
