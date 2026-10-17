---
type: intent
timestamp: 2026-10-16T234800
responding-to: PR #63 review findings at c04886d and operator guidance on container-readable runtime config
---

## Add regression tests for runtime readability and staging setup

Per operator request: I will add failing tests for two review findings before changing implementation: the runtime config must be readable by LiteLLM UID 1000 while the local overlay, env file, and LiteLLM host directory remain private; and isolated staging deployment must create its `litellm/local.env` before Compose starts. Runtime readability is safe only while config validation rejects literal credential values and requires environment references in credential fields. Success means both tests fail against the current branch for the reported reasons.
