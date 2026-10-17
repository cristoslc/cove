---
type: result
timestamp: 2026-10-17T040400Z
responding-to: parent symlink regression intent
commit: 29291df
---

## Parent-directory regressions are red

Per operator request: the new tests fail because CLI setup follows and chmods a symlinked `litellm` directory, Ansible still uses a path-based directory task, and staging lacks the trusted-directory helper. The companion configured-root test passes with a symlinked `COVE_DATA_ROOT`, pinning the compatibility rule that only Cove's `litellm` child must be real.
