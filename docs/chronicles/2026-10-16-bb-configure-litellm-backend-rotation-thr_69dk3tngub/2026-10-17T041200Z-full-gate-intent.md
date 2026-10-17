---
type: intent
timestamp: 2026-10-17T041200Z
responding-to: operator request for focused and full gates
---

## Run the full repository test gate

Per operator request: I will run Cove's prescribed project-local full unit/integration gate, excluding E2E and staging markers. Success means the full suite passes with the symlink setup, docs contracts, and existing feature coverage in the same run; no live stack or local configuration is touched.
