---
type: intent
timestamp: 2026-10-17T085730Z
responding-to: merged main now contains PR #64 and the stashed 0.14.0 release metadata
---

## Run the fresh main release gate

**Responding to:** merged main is at `3c54430`, and the named stash restored only `CHANGELOG.md`, `cli/pyproject.toml`, and `cli/uv.lock`.

Per operator request: run Cove's required non-E2E, non-staging test gate now, before resource sync, wheel build, commit, tag, install, or publish. Success means every test in the required gate passes on the exact merged main plus release metadata state.

**Commits in this unit:** none yet
