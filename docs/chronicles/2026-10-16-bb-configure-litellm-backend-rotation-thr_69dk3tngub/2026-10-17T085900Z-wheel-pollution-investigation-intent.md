---
type: intent
timestamp: 2026-10-17T085900Z
responding-to: first 0.14.0 wheel inspection found nested build entries
---

## Check the wheel for stale build pollution

**Responding to:** the 0.14.0 wheel contains the requested overlay helper, but its archive also contains 144 paths under `build/` after setuptools traversed nested `cli/build/lib` output.

Per operator request: determine whether these are stale generated artifacts or a packaging configuration defect, and rebuild from a clean generated build directory if safe. Success means the wheel retains the latest overlay helper without recursive `build/` entries; if not, stop before commit, tag, stable install, or publish.

**Commits in this unit:** none yet
