---
type: e2e
timestamp: 2026-10-17T083422Z
responding-to: isolated staging deploy and LiteLLM overlay smoke
---

## E2E chronicle

### Paths covered

| Path | Coverage | Result |
|------|----------|--------|
| LiteLLM base and local overlay merge precedence | covered | pass |
| LiteLLM local provider environment file injection | partial, fake placeholder reference only | pass |
| LiteLLM protected settings and credential validation | partial, valid overlay only | pass |
| LiteLLM container-readable runtime config in private host directory | covered | pass |
| LiteLLM external secret references in local configuration | partial, placeholder reference only | pass |
| Legacy config migration | not covered, no legacy file was supplied | N/A |
| `cove litellm up`, `down`, and `status` | not covered, the isolated Compose profile was started directly | N/A |
| GET `/health/readiness` through `litellm.cove` | covered | pass, HTTP 200 |
| GET `/v1/models` through `litellm.cove` | covered | pass, HTTP 200 |
| POST `/v1/chat/completions` | not covered, no provider request was made by design | N/A |
| ADE isolated staging health and Host routing | covered by stock staging suite | pass, 2 tests |
| ToolHive isolated staging health | covered by stock staging suite | fail, HTTP 502 |

### Test structure

The stock [`scripts/staging/e2e.sh`](https://git.cove/cristos/cove/src/branch/bb/configure-litellm-backend-rotation-thr_69dk3tngub/scripts/staging/e2e.sh) runs `pytest -x -q -m staging` against the two isolated ADE and ToolHive modules on port 9443. The additional LiteLLM smoke generated runtime YAML from the bundled base and a staging-only overlay, started the `litellm` Compose profile, probed health and model listing through nginx, and instantiated LiteLLM's `Router` twice with three local-only deployments. No completion endpoint or external provider endpoint was called.

### Results

The stock command exited 1 with 3 passed, 1 failed, and 3 warnings. The failing test was `test_health_route_answers`, which received HTTP 502 because ToolHive was restarting after reporting that no container runtime was available. The isolated ADE tests passed. LiteLLM and its staging database reached healthy state with zero LiteLLM restarts; readiness and authenticated model listing returned HTTP 200. The generated config contained three deployments, including two deployments under one alias and one fallback alias; both repeated `Router` parses succeeded. The staging LiteLLM directory was mode 0700, runtime YAML mode 0644, and env file mode 0600. One unauthenticated model-list probe returned 401 before a random staging-only proxy key was added; the authorized probe then passed. Startup also logged a non-fatal missing `opentelemetry` import for the optional Weave integration.

The stock test command does not test LiteLLM overlays: the live-targeted LiteLLM staging class points to port 443 and was not run. Legacy migration, invalid credential rejection, CLI lifecycle commands, blocked routes, and chat completions remain untested in this staging smoke.

**Commits in this unit:** e0b3dd1

### Final LiteLLM container diagnostic

After the initial health-starting observation, a read-only inspection found the isolated LiteLLM container healthy with restart count 0. Sanitized startup logs show `Proxy initialized with Config, Set models` and all three configured deployments, including both repeated-alias entries and the fallback. This confirms the placeholder configuration did not cause a parser or loader failure. The only error-level startup line was the non-fatal optional Weave integration import failure because `opentelemetry` is absent; readiness and model-list probes remained successful.
