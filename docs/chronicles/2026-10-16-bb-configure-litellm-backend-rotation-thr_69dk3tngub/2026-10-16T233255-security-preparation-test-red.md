---
type: checkpoint
timestamp: 2026-10-16T233255
responding-to: focused security and direct-start test run
---

## Security and direct-start checks identify four gaps

**Responding to:** the focused hardening test run and code review for Cove issue #62, “LiteLLM: add update-safe local config overlays”

The new run reports 4 failures and 1 pass. The generator accepts attempts to enable MCP or JWT auth and accepts literal credential values; `cove litellm up` also lacks runtime file preparation. Review found one more issue: generated `config.yaml` is mode 0644 even though it can contain migrated YAML, so it must be private. I will fix these paths and verify the red tests turn green before moving to operator documentation.

See [compose/litellm/config_overlay.py](https://git.cove.local/cristos/cove/src/branch/bb/configure-litellm-backend-rotation-thr_69dk3tngub/compose/litellm/config_overlay.py), [cli/cove/litellm.py](https://git.cove.local/cristos/cove/src/branch/bb/configure-litellm-backend-rotation-thr_69dk3tngub/cli/cove/litellm.py), and [cli/tests/test_litellm.py](https://git.cove.local/cristos/cove/src/branch/bb/configure-litellm-backend-rotation-thr_69dk3tngub/cli/tests/test_litellm.py).

**Commits in this unit:** 9866fec
