---
title: LiteLLM local config overlay
status: in progress
author: agent
created: 2026-10-16
tags: [litellm, configuration, sashay]
---

# LiteLLM local config overlay for issue #62

## Goal

Separate Cove-owned, updateable LiteLLM defaults from persistent operator-owned deployment configuration. The wheel and repository must not contain local deployments, aliases, routing, or fallback policy. Credentials stay in environment variables or a secret store and YAML refers to environment variables by name.

## Design

- Rename the bundled template as Cove's base config and retain only generic proxy security and behavior defaults there.
- Store the operator-owned overlay at `${COVE_DATA_ROOT}/litellm/config.local.yaml` and preserve it across upgrades.
- Generate `${COVE_DATA_ROOT}/litellm/config.yaml` as the runtime file consumed by the existing pinned LiteLLM 1.84.0 container.
- Do not rely on LiteLLM's native `include`: in 1.84.0 it extends top-level lists and replaces other top-level keys. That behavior does not give reliable nested precedence for this contract.
- Merge recursively for mappings. For `model_list`, concatenate base models followed by local models, preserving order and allowing duplicate `model_name` entries for LiteLLM router deployments. For all other lists, local values replace base values. Local scalar values replace base scalars. Explicit local nulls replace base values.
- Never deep-merge list items or model entries. The local operator can replace any base setting at its containing path.
- Keep the generated runtime file out of version control and mark it as generated. Do not store credentials in either YAML file; tests reject likely literal key values and confirm `os.environ/NAME` references remain intact.

## Migration

- On first upgrade, if `config.local.yaml` does not exist and the existing persistent `config.yaml` does, copy its bytes to `config.local.yaml` before generating the runtime file. This preserves the operator's customizations and lets those values take precedence over the new base; the legacy path is then replaced by the generated runtime config.
- Render the merged runtime `config.yaml` after migration and on every bring-up, so bundled base updates apply while local values persist.
- When neither local nor legacy config exists, seed a documented empty local overlay and render from base.
- Make migration idempotent. Never overwrite an existing local overlay, and fail loudly if migration cannot safely preserve the legacy file.
- Do not mutate live local config as part of this implementation; migration is exercised only in isolated tests and will happen on a later operator task.

## Work units

1. Add a failing test for config composition, local precedence, list handling, legacy migration, idempotence, and credential references. Update the coverage matrix.
2. Implement deterministic merge and migration/rendering in bringup IaC and wire the generated runtime file into Compose.
3. Update the LiteLLM config documentation with file ownership, precedence, migration, secret injection, and local-only routing guidance. Do not add deployment examples or model/provider values to repository files.
4. Run focused unit tests and the project test gate. Do not run `cove up`, mutate live config, reinstall the stable tool, or publish a release.

## Acceptance checks

- A release can update base defaults without losing operator YAML values.
- Existing config.yaml customizations survive migration byte-for-byte into config.local.yaml before composition.
- A second bring-up does not change local overlay contents.
- `model_list` supports repeated aliases for router balancing and fallbacks, while keeping every local deployment out of bundled source and wheel.
- Cove base security settings remain enabled; attempts to override the sealed settings are rejected.
- Secrets are referenced externally and no account-specific literal credential enters source, the wheel, tests, or example config.
- Tests cover success and rejected/unsafe migration paths; matrix rows reflect those flows.
