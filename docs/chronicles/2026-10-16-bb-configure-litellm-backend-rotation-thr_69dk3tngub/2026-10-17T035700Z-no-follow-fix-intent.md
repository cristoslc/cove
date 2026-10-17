---
type: intent
timestamp: 2026-10-17T035700Z
responding-to: operator request for symlink-safe env-file setup
---

## Secure local.env creation in both startup paths

Per operator request: I will add a shared no-follow env-file helper to `config_overlay.py`, call it from `cove litellm up` and `bringup.yml`, and add coverage that pins both call sites to the helper. Success means a symlink is rejected before chmod/read and a regular file is created or restricted to mode `0600`.
