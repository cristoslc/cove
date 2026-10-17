---
type: intent
timestamp: 2026-10-17T035300Z
responding-to: operator request for symlink hardening, configurable path docs, and changelog coverage
---

## Reject symlinked LiteLLM environment files

Per operator request: I will add a failing regression proving `local.env` symlinks are rejected without changing the target, then wire one no-follow creation helper into both CLI startup and Ansible bringup. Success means the env file remains private and a symlink target is never opened for setup.
