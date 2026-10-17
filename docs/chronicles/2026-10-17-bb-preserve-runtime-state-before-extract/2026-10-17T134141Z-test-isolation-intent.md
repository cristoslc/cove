---
type: intent
timestamp: 2026-10-17T13:41:41Z
responding-to: operator request to prevent CLI tests from extracting resources into the installed Cove home
---

## Isolate the `cove up` CLI tests before any gate

Per operator request: the `TestCoveUpCommand` tests use a temporary working directory but currently leave `ensure_init()` and the home directory unisolated. I will add a test fixture that redirects the Cove home to a temporary root and replaces resource initialization/re-extraction calls, then verify the installed resource directory manifest remains unchanged after the focused CLI tests.

**Commits in this unit:** none yet
