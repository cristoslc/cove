---
type: intent
timestamp: 2026-10-17T13:56:12Z
responding-to: reviewer finding on forced extraction retaining a valid marker after copy failure
---

## Invalidate the bundle marker before pruning

Per operator request: add a forced-copy failure regression where `.version` initially matches the current bundle. Safely remove the marker before pruning, write it only after all resources copy, and verify a subsequent `ensure_init()` retries and repairs the tree while `.env` and `nginx/default.conf` retain their inodes. Run the focused regression first, then the required gate with an installed-directory manifest comparison; do not mutate live services.
