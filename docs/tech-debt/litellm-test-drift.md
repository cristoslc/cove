# Pre-existing LiteLLM test failures (2026-07-26)

Discovered while running the full suite for the vault-CLI fix. These failures
exist on `main` at `cbe8abe` and are unrelated to the vault change.

## Failing tests (9-10)

- `tests/test_litellm.py::TestComposeServiceDefinitions::test_litellm_read_only`
- `tests/test_litellm.py::TestLitellmConfig::test_config_has_disable_admin_ui`
- `tests/test_litellm.py::TestLitellmConfig::test_config_has_disable_user_management`
- `tests/test_litellm.py::TestNginxConfig::test_health_route_allowed`
- `tests/test_litellm.py::TestNginxConfig::test_v1_models_route_allowed`
- `tests/test_litellm.py::TestNginxConfig::test_v1_prefix_route_allowed`
- `tests/test_litellm.py::TestNginxConfig::test_catch_all_returns_403`
- `tests/test_litellm.py::TestNginxRouteWhitelist::test_no_wildcard_proxy_pass`
- `tests/test_litellm.py::TestConfigTemplate::test_template_disables_admin_ui`
- `tests/test_litellm.py::TestAdversarial::test_admin_ui_disabled_in_config`

## Symptoms

The tests assert the LiteLLM compose service is `read_only: true` and that the
nginx config / LiteLLM config disable the admin UI and user management, with a
route-whitelisted proxy. The actual config drifts from these assertions.

## Likely cause

Recent LiteLLM work (commits `cb90fea`, `9e2ac5e`, `2a7b5dc`) changed the
compose template and config but did not update the tests, or vice-versa. The
tests encode a stricter posture than the deployed config.

## Reproduce

```
uv run --directory cli pytest -q tests/test_litellm.py
```

## Resolution

Investigate whether the config should be tightened to match the tests, or the
tests relaxed to match the current LiteLLM UI/PostgreSQL design (which may
require `read_only: false` and an enabled admin UI for Prisma migrations).