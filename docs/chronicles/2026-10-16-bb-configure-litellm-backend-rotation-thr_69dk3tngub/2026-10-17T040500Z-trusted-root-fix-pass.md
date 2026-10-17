---
type: result
timestamp: 2026-10-17T040500Z
responding-to: trusted-root fix intent
commit: f160de2
---

## Trusted-root checks pass in focused coverage

Per operator request: CLI, Ansible bringup, and isolated staging now use the shared descriptor-relative helper to create/open a real `litellm` child and private `local.env` without following child symlinks. The configured data root may itself be a symlink. Staging rejects equal or nested canonical live/staging roots before Docker or file setup. Focused LiteLLM and staging coverage passed: 123 passed, 8 E2E tests deselected.
