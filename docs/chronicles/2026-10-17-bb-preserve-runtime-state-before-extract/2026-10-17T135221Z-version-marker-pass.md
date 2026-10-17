---
type: verification
timestamp: 2026-10-17T13:52:21Z
responding-to: retained version marker safety intent
---

## Retained `.version` marker uses safe reads and atomic replacement

Per operator request: the new symlink regression failed before the change because extraction followed the `.version` symlink. Extraction, `ensure_init()`, and `maybe_reextract()` now read the marker through the descriptor-relative no-follow regular-file helper; FIFOs use nonblocking reads. After all bundle resources copy successfully, the new hash is written to a temporary file under the verified Compose directory and atomically replaces `.version`, so a partial copy leaves the old marker for retry. Focused resource tests and isolated CLI command tests pass: **43 passed**. No full gate was run while recovery is ongoing.
