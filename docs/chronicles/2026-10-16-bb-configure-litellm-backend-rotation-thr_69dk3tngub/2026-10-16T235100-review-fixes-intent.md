---
type: intent
timestamp: 2026-10-16T235100
responding-to: committed red regression tests
---

## Fix runtime readability and staging env preparation

Per operator request: I will render validated runtime YAML as `0644`, keep the LiteLLM host directory `0700`, retain `0600` on local overlay and env files, and create/chmod staging `litellm/local.env` before Compose runs. The config validator will remain the gate against literal values in credential-bearing fields. Success means UID 1000 can read the mounted runtime file while other host users cannot traverse its parent directory, and isolated staging no longer fails on a missing env file.
