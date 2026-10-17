---
type: intent
timestamp: 2026-10-17T08:25:00Z
responding-to: operator request for required test gates
---

## Run the required non-E2E and non-staging gate

Per operator request: I will sync the bundled compose resources from the source tree, then run the repository's required `uv run --directory cli pytest -x -q -m "not e2e and not staging"` gate. This does not deploy services or mutate live configuration.
