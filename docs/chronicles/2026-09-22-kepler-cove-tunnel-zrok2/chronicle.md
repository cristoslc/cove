# Chronicle — kepler/cove-tunnel-zrok2

Created: 2026-09-22
Plan: docs/plans/cove-tunnel-zrok2.md
Musing: docs/musings/cove-public-tunnels-bore-zrok.md (2026-09-22 update)

## Intent

Implement `cove tunnel` wrapping zrok2 (zrok.io hosted, free tier) per the plan:
sidecar container, tunnel-to-ingress, closed-by-default shares, `cove creds` auth.

## Entries

- 2026-09-22 (orchestrator): Sashay started. Plan committed on
  kepler/recommend-bore-vs-localhost-run (b522664); branch forked from it.
- 2026-09-22 (implementation): Core feature committed. `cove tunnel` command group
  (up/ls/down) in cli/cove/tunnel.py, registered in cli.py. zrok2 sidecar service in
  docker-compose.yml + canonical compose/tunnel.yml resource (profile: tunnel,
  outbound-only, no ports, image pinned to openziti/zrok2:2.0.4 by digest, read_only,
  state at ${COVE_DATA_ROOT}/tunnel). bringup.yml renders ZROK_ACCOUNT_TOKEN /
  ZROK_SHARE_NAME + data dir only when the tunnel profile is active; missing token
  fails loud with myzrok.io onboarding pointer. Auth via shared 1Password item
  op://Private/Zrok Account/account_token (ADR-017), env, or compose .env — never
  generated, never anonymous. Name validation: lowercase alnum 4-32 (zrok2 reserved
  names); public URLs under shares.zrok.io (v2 plural domain). 39 new unit tests in
  cli/tests/test_tunnel.py; full non-e2e suite 479 passed, 25 deselected. Docs at
  docs/services/tunnel.md (onboarding journey, v2 naming, private shares,
  interstitial caveat, cost ladder, localhost.run fallback).
