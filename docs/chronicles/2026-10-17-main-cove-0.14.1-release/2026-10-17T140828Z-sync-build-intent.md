---
type: intent
timestamp: 2026-10-17T140828Z
responding-to: required post-merge gate passed and installed Compose manifest matched
---

## Sync bundled Compose and build a clean 0.14.1 wheel

**Responding to:** the required gate passed with 790 tests and the installed Compose manifest stayed unchanged.

Per operator request: sync tracked Compose source into wheel resources, verify `cli/build` is untracked and ignored before removing only that directory, build the wheel with project-local `uv`, then inspect archive members for build pollution, required fixes, and local secrets/config.

**Commits in this unit:** none yet
