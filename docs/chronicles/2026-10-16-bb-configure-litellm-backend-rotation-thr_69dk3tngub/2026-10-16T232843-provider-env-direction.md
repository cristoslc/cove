---
type: decision
timestamp: 2026-10-16T232843
responding-to: operator clarification about provider credentials and router behavior
---

## Add a generic local provider environment file

**Responding to:** operator clarification for Cove issue #62, “LiteLLM: add update-safe local config overlays”

Per operator request: the overlay design must also make locally defined provider credentials available inside the LiteLLM container. Compose currently forwards only `OLLAMA_API_KEY`, so I will add an operator-owned environment file under Cove's persistent LiteLLM data directory and inject it at runtime without placing credential values in YAML or the wheel. The docs will explain that duplicate `model_name` entries form a load-balanced group and `router_settings.fallbacks` configures fallback across groups. Success means overlay references to arbitrary provider environment variable names can resolve without provider-specific names in Cove code.

**Commits in this unit:** 12bd4f7
