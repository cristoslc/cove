---
type: checkpoint
timestamp: 2026-10-17T090054Z
responding-to: operator requested tag and stable install after the required gate and clean wheel verification
---

## 0.14.0 tag and stable install verified

**Responding to:** the release commit was pushed to `origin/main`, and the clean wheel passed version and overlay-helper checks.

Per operator request: created annotated tag `v0.14.0` on release commit `628df292e7e554aad1eb458606c69f63e6190d73`. Installed only `cli/dist/cove_cli-0.14.0-py3-none-any.whl` with uv after the required gate; `cove --version` reports 0.14.0. The tag has not yet been pushed; dual-host publication is next.

**Commits in this unit:** none yet
