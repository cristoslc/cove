---
type: checkpoint
timestamp: 2026-10-17T08:26:09Z
responding-to: FIFO open fix intent
---

## Nonblocking FIFO validation passes focused regressions

Per operator request: config and env regular-file read opens now include `O_NONBLOCK` with `O_NOFOLLOW`, including local-overlay reopen after a create race. FIFO paths therefore reach the regular-file check without waiting for a peer. Focused security tests passed: 7 passed, 117 deselected.
