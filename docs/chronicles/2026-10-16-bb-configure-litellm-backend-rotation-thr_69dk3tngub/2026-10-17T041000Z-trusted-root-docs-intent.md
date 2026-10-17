---
type: intent
timestamp: 2026-10-17T041000Z
responding-to: trusted-root review fix
---

## Document the trusted-root boundary

Per operator request: I will document that configured data roots may be symlinks, while Cove requires its `litellm` child to be a real directory and staging rejects canonical live-root overlap. Success means operators can use legitimate mounted roots without leaving the symlink boundary ambiguous.
