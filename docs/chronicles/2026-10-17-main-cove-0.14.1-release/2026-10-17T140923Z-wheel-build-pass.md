---
type: checkpoint
timestamp: 2026-10-17T140923Z
responding-to: Compose sync and clean wheel build intent
---

## Compose resources synced and release wheel verified

**Responding to:** the operator asked for a clean build after confirming the stale `cli/build` directory was ignored and untracked.

Per operator request: Compose resources synced with no tracked resource delta. The verified stale `cli/build` directory was removed, then `uv build --wheel --out-dir dist` produced `cove_cli-0.14.1-py3-none-any.whl` (109 members, SHA-256 `aa98695849c65b742d659d5ff5329aa974f04c21f692b89de37ff5108e2f8586`). Archive inspection found zero `build/` paths and zero machine-local config/secret filenames. It contains Compose preservation code, the 3600-second LiteLLM streaming template, the generic LiteLLM overlay helper and base config. The base config has an environment reference for its master key and no `model_list`.

The first inventory check used the wrong expected base-config filename; inspection confirmed the bundled Cove file is `config.base.yaml`, and the corrected archive checks passed.

**Commits in this unit:** none yet
