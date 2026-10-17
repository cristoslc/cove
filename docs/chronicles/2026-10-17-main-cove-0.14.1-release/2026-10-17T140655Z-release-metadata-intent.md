---
type: intent
timestamp: 2026-10-17T140655Z
responding-to: operator authorization to release Cove 0.14.1 from main at 1c900d6
---

## Prepare the 0.14.1 release metadata

**Responding to:** the operator authorized release 0.14.1 from the clean merged main checkout and required both Unreleased fixes to move into the dated release notes.

Per operator request: bump the Cove package and lock versions to 0.14.1, move the LiteLLM streaming and runtime Compose preservation fixes into the 2026-10-17 changelog section, and leave a fresh Unreleased heading. Success means the package metadata and lock agree and only these intended release files change before the gate.

**Commits in this unit:** none yet
