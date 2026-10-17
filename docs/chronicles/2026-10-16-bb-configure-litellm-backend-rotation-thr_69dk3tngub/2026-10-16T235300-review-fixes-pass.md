---
type: checkpoint
timestamp: 2026-10-16T235300
responding-to: runtime readability and staging env implementation
---

## Runtime and staging regressions pass

Per operator request: runtime YAML is now written `0644` only after credential-field validation, while the LiteLLM host directory is kept `0700` and `config.local.yaml` plus `local.env` remain `0600`. The generator repairs runtime permissions even when content is unchanged. `deploy-isolated.sh` now creates its private LiteLLM directory and `local.env` before Compose startup. The full project-local non-E2E/non-staging gate passes: 762 passed, 31 deselected, five getpass warnings. No E2E run or live state change occurred.
