---
type: checkpoint
timestamp: 2026-10-16T233358
responding-to: focused security and LiteLLM test run
---

## Security guards and direct startup pass

**Responding to:** the corrected guard tests and focused LiteLLM/ToolHive suites for Cove issue #62, “LiteLLM: add update-safe local config overlays”

The hardening tests now pass, including rejection of attempts to enable MCP or JWT auth and literal credential values, while allowing `os.environ/NAME` references without printing values. Generated config and the provider env file use mode 0600. `cove litellm up` now prepares the same runtime files as bringup, so it can start the service without a previous `cove up`. Focused regression suites passed: 150 passed, 8 deselected.

See [compose/litellm/config_overlay.py](https://git.cove.local/cristos/cove/src/branch/bb/configure-litellm-backend-rotation-thr_69dk3tngub/compose/litellm/config_overlay.py), [cli/cove/litellm.py](https://git.cove.local/cristos/cove/src/branch/bb/configure-litellm-backend-rotation-thr_69dk3tngub/cli/cove/litellm.py), and [docs/test-coverage-matrix.yaml](https://git.cove.local/cristos/cove/src/branch/bb/configure-litellm-backend-rotation-thr_69dk3tngub/docs/test-coverage-matrix.yaml).

**Commits in this unit:** 9866fec
