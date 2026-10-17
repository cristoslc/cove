---
type: verification
timestamp: 2026-10-17T13:43:29Z
responding-to: test isolation intent before any required gate
---

## CLI resource setup tests isolated from the installed home

Per operator request: I added a fixture for `TestCoveUpCommand` and `TestNoUpgradeFlag` that redirects `Path.home()` to a per-test temporary directory and replaces both `ensure_init()` and `maybe_reextract()`. The focused command ran 16 tests successfully. A before/after manifest of `~/.config/cove/compose` (names, types, modes, sizes, timestamps, and content hashes) was identical; the installed directory was untouched. The live `.env` is currently absent, so none was read.
