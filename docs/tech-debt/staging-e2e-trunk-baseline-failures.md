# Tech Debt: Staging E2E baseline failures — litellm auth drift (ab01427) + speedtest APP_KEY gating

**Filed:** 2026-09-22
**Severity:** Medium (staging tier-2 gate is red on trunk; new sashays can't get a clean E2E signal)
**Status:** Open

## Symptom

`pytest -m staging` against the live stack fails 8 tests on **pristine trunk**
(`fjl/main` @ 0886151) — verified in a throwaway worktree during the cove-tunnel
sashay (PR #53), so the failures are baseline, not branch-caused:

- `test_litellm.py::TestE2ELitellmStack` — 6 of 8 fail:
  - `test_models_endpoint_returns_200` — expects unauthenticated 200 on
    `/v1/models`; trunk commit ab01427 ("enable LiteLLM admin UI — master key
    auth") made LiteLLM require `Authorization: Bearer <LITELLM_MASTER_KEY>`.
    With a key the endpoint returns 200; without, 401. Test is stale.
  - `test_key_generate_blocked_with_403`, `test_user_new_blocked_with_403`,
    `test_prompts_test_blocked_with_403` — expect nginx route-whitelist 403s;
    ab01427 **removed the route whitelist** and proxies all paths. The 403
    posture now comes (if at all) from LiteLLM's own auth, not nginx.
  - `test_container_is_read_only` — trunk's litellm compose service has no
    `read_only: true`; test asserts it does.
  - `test_wrong_host_header_returns_444` — expects nginx 444 default-server
    behavior that the post-ab01427 nginx config no longer implements.
- `test_speedtest.py::TestE2ESpeedtestStack` — 2 fail:
  - `test_speedtest_ui_returns_200`, `test_speedtest_requires_auth` — the
    speedtest container is unhealthy because `SPEEDTEST_APP_KEY` comes from
    1Password (`Cove Admin`/`Speedtest Tracker` items, ADR-017) and staging
    deploy didn't provide it; deploy.sh sets a random env override that may not
    satisfy the auth-flow expectations.

## Root causes

1. **Test-vs-config drift:** the litellm E2E tests were written against the
   route-whitelist + unauthenticated-models world (8ec9094, 2026-07-24); ab01427
   (2026-07-25) changed the security posture without updating the E2E tier.
2. **Credential-dependent E2E:** speedtest E2E assumes the operator's shared
   1Password items are present/cached; a fresh staging run without them can't
   pass. Needs an explicit precondition check that fails loud with setup
   instructions (or a documented skip reason), not a raw 200-assert.

## Fix direction

- Update `test_models_endpoint_returns_200` to authenticate with the master key
  resolved from the compose `.env` / Vault (fail loud if absent), or assert 401
  when no key is configured (pick one posture and assert it).
- Re-assert the actual post-ab01427 security posture: admin routes now
  authenticated by LiteLLM master key (assert 401 without key, 200/403 with
  key as the config dictates), or restore nginx-layer blocks if the operator
  wants defense-in-depth back.
- For `read_only` / host-444: either restore the compose/nginx hardening or
  update the tests to the accepted posture — decide, don't leave both drifting.
- Speedtest E2E: add a precondition step that runs `cove creds` flow (or skips
  with a loud, explicit reason) when the APP_KEY isn't available.
- Consider a "staging baseline" chronicle note in each sashay handoff until the
  tier is green again, so trunk-baseline noise isn't re-diagnosed per-sashay.

## Repro (2026-09-22)

```
scripts/staging/setup.sh kepler/cove-tunnel-zrok2
scripts/staging/deploy.sh kepler/cove-tunnel-zrok2
scripts/staging/e2e.sh kepler/cove-tunnel-zrok2   # 8 failed, 14 passed
# same failures on pristine fjl/main worktree against the same live stack
scripts/staging/teardown.sh kepler/cove-tunnel-zrok2
```

Evidence chronicle: `docs/chronicles/2026-09-22-kepler-cove-tunnel-zrok2/chronicle.md`
(staging entry, PR #53 comments).