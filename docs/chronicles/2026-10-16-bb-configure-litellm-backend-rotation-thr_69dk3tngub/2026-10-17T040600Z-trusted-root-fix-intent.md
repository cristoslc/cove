---
type: intent
timestamp: 2026-10-17T040600Z
responding-to: parent symlink regressions
---

## Enforce the trusted-root boundary in all setup paths

Per operator request: I will add descriptor-relative no-follow handling for the `litellm` child directory and `local.env`, then wire it into CLI, bringup, and staging. The configured root itself may resolve through a symlink; staging will reject canonical live/staging root overlap before creating files or starting Compose.
