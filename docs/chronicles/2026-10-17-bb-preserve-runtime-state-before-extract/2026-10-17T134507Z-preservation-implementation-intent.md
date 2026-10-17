---
type: intent
timestamp: 2026-10-17T13:45:07Z
responding-to: operator request to safely preserve .env and generated nginx config across extraction
---

## Initial preservation implementation intent (superseded before implementation)

Per operator request: the initial approach considered an external private temporary backup. Parent review then required stable inodes and safety on source-copy failure; this approach was superseded by the in-place pruning design recorded in `2026-10-17T134711Z-inode-failure-intent.md`. The implementation does not stage runtime bytes or remove/recreate the allowlisted paths.
