---
type: intent
timestamp: 2026-10-17T08:25:18Z
responding-to: operator FIFO blocking security review
---

## Reject FIFO config paths without blocking

Per operator request: I will add subprocess timeout regressions for FIFO paths at `local.env`, local overlay, runtime output, and legacy migration input. Each case must terminate promptly with a regular-file validation error. Then I will add `O_NONBLOCK` to no-follow read opens so a FIFO cannot stall before `fstat` rejects it.
