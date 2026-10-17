---
type: intent
timestamp: 2026-10-17T13:54:24Z
responding-to: parent recovery-complete gate approval
---

## Run the required gate with installed-resource manifest comparison

Per operator request: parent recovery is complete and paused. The temp-root preservation regressions and CLI test isolation are ready. I will snapshot the installed `~/.config/cove/compose` manifest without printing file contents, run `uv run --directory cli pytest -x -q -m "not e2e and not staging"`, then snapshot and compare the installed directory again. No live Cove commands or deployments will run.
