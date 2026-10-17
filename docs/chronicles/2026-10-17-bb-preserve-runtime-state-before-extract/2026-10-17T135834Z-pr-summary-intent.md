---
type: intent
timestamp: 2026-10-17T13:58:34Z
responding-to: marker invalidation review correction
---

## Correct the draft PR summary after marker invalidation

Per operator request: update PR #66 to reflect the implemented retry contract: `.version` is invalidated before pruning and absent after copy failure; the next `ensure_init()` repairs the bundle. Refresh the focused/full gate counts and manifest status without changing the draft state.
