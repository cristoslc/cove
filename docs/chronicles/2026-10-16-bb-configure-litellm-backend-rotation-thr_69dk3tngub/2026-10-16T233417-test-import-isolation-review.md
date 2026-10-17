---
type: review-response
timestamp: 2026-10-16T233417
responding-to: style review of the focused test changes
---

## Isolate the config helper import in tests

**Responding to:** style review of Cove issue #62, “LiteLLM: add update-safe local config overlays”

The review found that adding the Compose directory to global `sys.path` during test collection could alter imports elsewhere in the suite. I will load the generator module directly by file path under a test-specific name, then rerun the relevant tests. The review also found the operator guide still describes the old config behavior; that documentation gap is the next work unit.

See [cli/tests/test_litellm.py](https://git.cove.local/cristos/cove/src/branch/bb/configure-litellm-backend-rotation-thr_69dk3tngub/cli/tests/test_litellm.py) and [docs/services/litellm-proxy.md](https://git.cove.local/cristos/cove/src/branch/bb/configure-litellm-backend-rotation-thr_69dk3tngub/docs/services/litellm-proxy.md).

**Commits in this unit:** 9866fec
