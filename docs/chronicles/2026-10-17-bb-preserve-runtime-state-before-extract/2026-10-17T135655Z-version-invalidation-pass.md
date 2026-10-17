---
type: verification
timestamp: 2026-10-17T13:56:55Z
responding-to: version invalidation regression intent
---

## Failed forced extraction invalidates the marker and remains repairable

Per operator request: both new forced-copy failure cases failed before the fix because the previous bundle marker remained. Extraction now safely unlinks the validated marker before pruning and atomically writes it only after all copies succeed. The new regression starts with a marker matching the current bundle, injects a partial copy failure, verifies `.version` is absent while `.env` and nginx bytes/inodes remain, then confirms `ensure_init()` retries and restores fresh pins and the marker. The focused resource and CLI isolation set passes: **44 passed**. The plan and incident log now reflect marker invalidation. No live mutation occurred.
