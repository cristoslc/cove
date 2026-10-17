---
type: checkpoint
timestamp: 2026-10-17T040000Z
responding-to: repeated model group and fallback contract coverage
---

## Router group contract passes

Per operator request: composition tests now retain repeated `model_name` entries in order and preserve local `router_settings.fallbacks`. Documentation links the pinned LiteLLM 1.84.0 Router source example that demonstrates repeated deployment names and cross-group fallbacks. Full project gate passes: 759 passed, 31 deselected, with five getpass warnings. No E2E run or live state change occurred.
