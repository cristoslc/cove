---
type: intent
timestamp: 2026-10-17T08:26:00Z
responding-to: FIFO regression red checkpoint
---

## Make regular-file validation nonblocking

Per operator request: I will add `O_NONBLOCK` to all `O_NOFOLLOW | O_RDONLY` opens used for config and environment file validation, including the concurrent local-overlay reopen. Then I will rerun the FIFO regressions before the complete required gate.
