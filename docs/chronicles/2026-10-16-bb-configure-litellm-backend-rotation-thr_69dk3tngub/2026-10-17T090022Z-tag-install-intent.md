---
type: intent
timestamp: 2026-10-17T090022Z
responding-to: release commit 628df29 was pushed to origin main
---

## Tag and install the verified 0.14.0 wheel

**Responding to:** the required gate passed, the rebuilt wheel is clean and contains the LiteLLM overlay helper, and release commit `628df29` is pushed to Forgejo `origin/main`.

Per operator request: confirm `v0.14.0` is unused, create an annotated tag on release commit `628df29`, then install the verified wheel into the stable uv tool and confirm its reported version. Success means the tag points to that release commit and the installed `cove` reports 0.14.0; publishing follows as a separate work unit.

**Commits in this unit:** none yet
