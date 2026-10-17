---
type: intent
timestamp: 2026-10-17T13:57:13Z
responding-to: operator request to rerun the required gate after marker invalidation fix
---

## Re-run the full gate after marker invalidation

Per operator request: the marker invalidation fix and focused regressions are committed and pass. Capture a fresh installed Compose manifest, run the required non-E2E/non-staging gate, then capture and compare the manifest again. Keep file contents private and do not run live Cove commands or deployments.
