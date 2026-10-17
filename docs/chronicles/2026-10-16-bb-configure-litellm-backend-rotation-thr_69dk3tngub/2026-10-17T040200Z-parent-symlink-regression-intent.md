---
type: intent
timestamp: 2026-10-17T040200Z
responding-to: operator security re-review at dc0d037
---

## Pin parent-directory symlink rejection

Per operator request: I will add failing regressions for a symlinked `litellm` parent in CLI setup and isolated staging before changing the implementation. The tests will preserve the configured data-root symlink allowance while requiring Cove-owned `litellm` directories to be real directories, and will check staging's canonical root isolation.
