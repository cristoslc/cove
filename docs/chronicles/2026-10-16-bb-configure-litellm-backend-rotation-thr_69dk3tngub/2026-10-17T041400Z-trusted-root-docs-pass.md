---
type: result
timestamp: 2026-10-17T041400Z
responding-to: trusted-root docs intent
commit: 046f73e
---

## Trusted-root behavior is documented

Per operator request: the service guide now states that a configured data root may be a symlink, Cove's `litellm` child must be a real directory, and staging rejects canonical overlap with live data. The focused docs, parent-symlink, and staging contract checks passed: 4 passed.
