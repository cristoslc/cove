---
type: intent
timestamp: 2026-10-17T041400Z
responding-to: full gate finding bundled bringup mismatch
---

## Sync bundled Cove resources and rerun the gate

Per operator request: the full gate found `compose/bringup.yml` differs from the bundled wheel resource copy. I will run the repository resource sync script so the checked-in wheel payload includes the safe bringup helper, then rerun the prescribed full gate. This is a source-tree synchronization step only; it does not build, install, or publish a wheel.
