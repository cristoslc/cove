---
type: teardown
timestamp: 2026-10-17T0835Z
responding-to: isolated staging teardown after E2E and LiteLLM overlay smoke
---

## Teardown result

Ran `env -i HOME="$HOME" PATH="$PATH" ./scripts/staging/teardown.sh bb/configure-litellm-backend-rotation-thr_69dk3tngub`; it exited 0 and removed the staging root and staging venv. Verification found that the script left `cove-staging-litellm`, `cove-staging-litellm-db`, and `cove-staging_default`, because its Compose `down` enables `ade` and `mcp` profiles but omits `litellm`.

Removed only those remaining isolated resources with `env -i HOME="$HOME" PATH="$PATH" docker compose -p cove-staging -f compose/docker-compose.yml -f compose/docker-compose.staging.yml --profile litellm down -v --remove-orphans`; it exited 0. Final checks found zero containers labeled `com.docker.compose.project=cove-staging`, no `cove-staging_default` network, no `cove-staging` volumes, no default staging root, and no `.staging-venv`. The live data root remained present and all 13 live Cove containers remained running. No live service was changed.

This reveals a teardown profile omission in the branch. No code changes were made during staging or cleanup.

**Commits in this unit:** 0cda81e
