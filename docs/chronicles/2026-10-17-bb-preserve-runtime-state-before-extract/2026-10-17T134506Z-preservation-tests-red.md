---
type: verification
timestamp: 2026-10-17T13:45:06Z
responding-to: runtime preservation regression intent
---

## Runtime preservation tests fail before the fix

Per operator request: temp-root regressions now cover both forced extraction and bundle-hash re-extraction, exact `.env` and generated nginx bytes/modes, refreshing bundled Compose pins/template, rejecting symlinked preserved files before tree removal, and rejecting a FIFO without blocking. All five cases fail against the current implementation, as expected. These tests operate only under pytest temporary directories.
