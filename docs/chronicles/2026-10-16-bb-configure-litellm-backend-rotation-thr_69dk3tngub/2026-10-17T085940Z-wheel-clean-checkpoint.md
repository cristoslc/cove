---
type: checkpoint
timestamp: 2026-10-17T085940Z
responding-to: stale cli/build directory caused nested build paths in the first wheel
---

## Clean 0.14.0 wheel verified

**Responding to:** first wheel inspection found 144 `build/` archive paths, while the requested LiteLLM overlay helper was present.

Per operator request: `git ls-files cli/build` was empty, so I removed the ignored generated directory with a path-checked operation and rebuilt. The rebuilt `cli/dist/cove_cli-0.14.0-py3-none-any.whl` declares version 0.14.0, includes `cove/resources/compose/litellm/config_overlay.py`, and has zero `build/` archive entries. The polluted artifact was not promoted or published.

**Commits in this unit:** none yet
