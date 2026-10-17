---
type: checkpoint
timestamp: 2026-10-17T08:24:00Z
responding-to: config file symlink security regression intent
---

## Config file symlink regressions reproduce the issue

Per operator request: the new focused test failed in all three cases. `generate_runtime_config` accepted symlinks for the local overlay, existing runtime file, and legacy migration source. The cases also check an external target's bytes and mode, so the implementation must reject before reading or changing it.

The initial pytest invocation used a repo-relative path even though `uv --directory cli` changes the test root; the corrected command was `uv run --directory cli pytest -q tests/test_litellm.py -k rejects_symlinked_config_files_without_touching_target`.
