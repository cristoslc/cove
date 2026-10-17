---
type: result
timestamp: 2026-10-17T035500Z
responding-to: symlink regression intent
commit: aa8e50e
---

## Symlink regression is red

Per operator request: the new CLI regression uses an external target with known content and mode, then requires setup to reject `local.env` when it is a symlink. It failed against the current implementation because setup did not raise; the captured `updated` output confirms config generation proceeded after following the link. The test was committed before the fix.
