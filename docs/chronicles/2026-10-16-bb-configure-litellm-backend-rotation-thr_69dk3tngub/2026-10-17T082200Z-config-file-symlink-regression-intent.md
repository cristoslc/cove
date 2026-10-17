---
type: intent
timestamp: 2026-10-17T08:22:00Z
responding-to: operator request for config.local.yaml and runtime/legacy config path hardening
---

## Reject symlinked Cove-owned LiteLLM config files

Per operator request: I will add targeted regressions for symlinked local, runtime, and legacy config files, including a check that an external target stays byte-for-byte and mode unchanged. Then I will replace path-following checks and reads in runtime generation with descriptor-relative no-follow operations inside the validated LiteLLM directory.
