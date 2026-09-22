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
- 2026-09-22 (implementation): `tunnel ls` switched from `agent status` to
  `zrok2 list shares` (the v2.0 listing verb, per the zrok2 CLI reference). PR
  comment for a6f1596 posted 3 times due to silent fj success + re-runs; noted,
  no action needed (duplicate comments only).
- 2026-09-22 (implementation): Verified resource sync (compose/tunnel.yml lands in
  cli/cove/resources/compose; dir is gitignored, sync runs at wheel build). PR comment
  for 9e1555a posted (1 copy). Full non-e2e suite re-run: 479 passed, 25 deselected.
- 2026-09-22 (implementation): Wrap-up. `docker compose --profile tunnel config`
  validates (outbound-only service rendered with digest pin + data-root bind).
  Branch pushed to origin; PR #53 has 6 comments (3 duplicates of the a6f1596
  entry from silent fj success + re-runs). Scope complete per plan: command group,
  compose resource, bringup gating, loud auth, tests, docs. Deferred to orchestrator:
  e2e relay-touching tests (gated), promote/reinstall (post-merge), operator zrok
  signup + token provisioning.

- 2026-09-22 (orchestrator): Closure loop. Rebased onto fjl/main (0886151) via sync,
  force-pushed. Coverage matrix self-healed: 7 tunnel paths added (83a6060). Test gate:
  481 passed. Code review (orchestrator-run; subagent dispatch erroring in harness):
  findings = docs/error text referenced nonexistent `cove creds set` (fixed ->
  `cove creds vault-put`), URL domain was `shares.zrok.io` vs zrok2's documented
  `share.zrok.io` (red-green: failing test first, then fixed ZROK2_DOMAIN + docs),
  minor nits accepted (status-grep idempotency guard, unused SHARE_TOKEN_OP_REF,
  tunnel.yml networks key). Post-fix gate: 482 passed.
