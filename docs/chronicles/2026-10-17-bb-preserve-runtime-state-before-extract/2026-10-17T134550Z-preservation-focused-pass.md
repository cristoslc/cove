---
type: verification
timestamp: 2026-10-17T13:45:50Z
responding-to: runtime preservation implementation intent
---

## Runtime preservation regressions pass in temporary roots

Per operator request: the new resource tests and the isolated `cove up` callback tests passed together: **21 passed**. Coverage includes forced and hash-change extraction, byte/mode preservation for `.env` and generated nginx config, refresh of bundled Compose pins/template, symlink rejection before deletion, and a five-second FIFO subprocess timeout. The resource tests use pytest temporary roots; no live service or deploy command was run.
