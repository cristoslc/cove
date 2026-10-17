---
type: intent
timestamp: 2026-10-16T232907
responding-to: red overlay contract tests and operator credential clarification
---

## Implement safe runtime config generation

**Responding to:** the failing overlay contract tests and operator clarification about local provider credentials for Cove issue #62, “LiteLLM: add update-safe local config overlays”

Per operator request: I will remove deployment-specific models from the bundled base, implement validated recursive merging and idempotent legacy migration, run it from bringup, and inject a persistent local provider env file into the LiteLLM container. The generated runtime config will use explicit precedence and atomic writes. Success means Cove can update generic defaults while retaining local config and credential files, with invalid YAML failing before runtime replacement.

**Commits in this unit:** 2a0d14b
