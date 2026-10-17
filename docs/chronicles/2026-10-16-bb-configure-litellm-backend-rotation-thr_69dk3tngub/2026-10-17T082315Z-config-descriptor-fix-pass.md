---
type: checkpoint
timestamp: 2026-10-17T08:23:15Z
responding-to: config descriptor fix intent
---

## No-follow config reads and migration pass focused tests

Per operator request: local overlay, runtime, and legacy config files now open relative to the LiteLLM directory descriptor with `O_NOFOLLOW`; reads verify regular-file type, local mode changes use the opened descriptor, and runtime output replacement stays relative to that descriptor. The bundled base config is opened as a no-follow regular file. CLI and Ansible both pass the configured data root for directory validation.

The new symlink regressions passed, including unchanged external target bytes and mode. The focused Cove LiteLLM suite passed: 112 passed, 8 E2E tests deselected. A prior unfiltered invocation mistakenly reached live E2E read checks and reported endpoint-dependent failures; no services or config were changed.
