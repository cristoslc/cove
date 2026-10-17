---
type: verification
timestamp: 2026-10-17T13:49:39Z
responding-to: runtime inode and copy-failure intent
---

## In-place preservation and failure regressions pass

Per operator request: the first regression run exposed the reviewed defects: three failures showed both runtime inodes changing and `.env` disappearing after an injected copy failure. Extraction now prunes non-allowlisted resources in place, retains `.env`, `nginx/default.conf`, and the old `.version` until bundle copying succeeds, and skips those exact paths while copying. Descriptor-relative no-follow validation rejects symlinked runtime files, `nginx` parents, and a symlinked Compose parent; FIFO checks stay nonblocking. The `.env` mode is restricted to owner-only without replacing its inode. The temp-root resource tests plus isolated `TestCoveUpCommand` and `TestNoUpgradeFlag` checks pass: **41 passed**. The full gate is intentionally pending parent recovery; no live resources or services were touched.
