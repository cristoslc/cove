---
type: checkpoint
timestamp: 2026-10-16T235000
responding-to: runtime readability and staging local.env regression tests
---

## Review regression tests fail as expected

Per operator request: the new regression tests fail against the current implementation. The runtime YAML is still mode `0600` instead of container-readable `0644`, direct CLI preparation leaves the LiteLLM data directory at its default mode instead of `0700`, and `deploy-isolated.sh` does not create the staging `litellm/local.env`. The focused run reports 3 failed. I will now make the runtime YAML readable only within the private host directory, keep local overlay and env files at `0600`, and seed the staging env file before Compose startup.
