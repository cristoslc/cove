---
type: result
timestamp: 2026-10-17T040800Z
responding-to: staging symlink regression intent
commit: 7a44af8
---

## Staging uses the shared no-follow helper

Per operator request: isolated staging now invokes `config_overlay.py --ensure-env-file` before Compose starts, replacing direct `touch`/`chmod`. The staging contract executes the helper against a symlink and confirms its target content and mode remain unchanged. Focused CLI and staging checks passed: 3 passed.
