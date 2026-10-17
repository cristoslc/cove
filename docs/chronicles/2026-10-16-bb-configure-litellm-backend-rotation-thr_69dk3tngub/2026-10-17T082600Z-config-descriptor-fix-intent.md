---
type: intent
timestamp: 2026-10-17T08:26:00Z
responding-to: config file symlink regressions
---

## Open Cove-owned config files relative to validated directories

Per operator request: I will make config generation anchor local, runtime, and legacy files to the validated LiteLLM directory, open each with `O_NOFOLLOW`, and require regular files before reading or changing modes. The base config will also be read through a no-follow regular-file descriptor. I will remove `exists()`, `read_bytes()`, and `stat()` checks from the config generation and CLI result-reporting paths where they could follow links.
