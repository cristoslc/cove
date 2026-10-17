---
type: intent
timestamp: 2026-10-16T233200
responding-to: review of config security invariants
---

## Lock Cove security settings and external credentials

**Responding to:** review of the runtime config merge for Cove issue #62, “LiteLLM: add update-safe local config overlays”

Per operator request: I will add contract tests that reject local changes which re-enable LiteLLM MCP or JWT auth and reject literal values in credential fields, while allowing environment references. Errors must identify the config path without echoing the credential. Success means the reviewed security rules are enforced before runtime config replacement.

**Commits in this unit:** 9866fec
