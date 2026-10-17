---
type: verification
timestamp: 2026-10-17T13:58:20Z
responding-to: full-gate rerun intent after marker invalidation
---

## Required gate passed after marker invalidation

Per operator request: `uv run --directory cli pytest -x -q -m "not e2e and not staging"` passed after the forced-copy marker fix: **789 passed, 31 deselected**, with five `getpass` terminal warnings. The installed Compose manifest was captured before and after without printing file contents: 77 entries and identical digest `a606bc769a4e1b6d214009516d94db9e7f353df2c27d5cc078ab1d0ba20ee552`; comparison confirms it is unchanged. No live Cove command, deployment, or service mutation ran.
