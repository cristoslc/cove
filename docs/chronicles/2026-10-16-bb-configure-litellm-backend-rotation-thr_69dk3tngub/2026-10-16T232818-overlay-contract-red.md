---
type: checkpoint
timestamp: 2026-10-16T232818
responding-to: focused overlay contract test run
---

## Overlay contract tests expose the current coupling

**Responding to:** the focused test run for Cove issue #62, “LiteLLM: add update-safe local config overlays”

The first pytest invocation used a repo-relative path while `uv --directory cli` had already changed directories, so it collected no tests. With the corrected path, the new suite reported 6 failures and 7 passes: the bundled template still contains operator model deployments, and the composition/migration helper is not implemented yet. The matrix now includes migration, precedence, and external-secret paths. Tests and matrix changes are ready to commit before implementation.

See [cli/tests/test_litellm.py](https://git.cove.local/cristos/cove/src/branch/bb/configure-litellm-backend-rotation-thr_69dk3tngub/cli/tests/test_litellm.py) and [docs/test-coverage-matrix.yaml](https://git.cove.local/cristos/cove/src/branch/bb/configure-litellm-backend-rotation-thr_69dk3tngub/docs/test-coverage-matrix.yaml).

**Commits in this unit:** d69a517
