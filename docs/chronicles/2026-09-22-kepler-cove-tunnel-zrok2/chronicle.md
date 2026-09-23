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

- 2026-09-22 (orchestrator): Staging deploy + E2E. Deploy OK (wheel build, cove up
  re-rendered nginx — note: default.conf was missing on the deployed stack until a
  manual `.staging-venv/bin/cove up` re-ran the render; deploy.sh's cove up had
  aborted on the BECOME prompt in non-interactive mode). E2E: DNS suite green
  (config/ca fixed by re-render). Staging-marked suites: test_litellm E2E failures
  (6) reproduce IDENTICALLY on pristine fjl/main (verified in a throwaway worktree
  with the same live stack) — pre-existing on trunk, not caused by this branch:
  test_models_endpoint expects unauthenticated 200 but trunk commit ab01427
  (admin-UI/master-key auth) now requires a Bearer key; the /key/generate, /user/new,
  /prompts/test 403 tests and read_only/444 checks likewise mismatch the current
  stack (route-whitelist removal, no read_only in compose). test_speedtest failures
  are also stack-state (speedtest unhealthy pending APP_KEY from 1Password). None of
  the failing paths touch tunnel code. Escalation guard not triggered — these are
  trunk-baseline failures, recorded here and for the operator handoff.

- 2026-09-22 (impl agent): Operator-rework implementation (picker + Cove-managed
  share routes). Two behaviors from the operator review replaced in-place:
  (1) silent `DEFAULT_TARGET` removed — `discover_services()` parses the nginx
  ingress config (rendered `default.conf` preferred, `.j2` fallback) into a
  service inventory (upstreams + `set $var` resolvers + static landing/pages
  bodies; regex-only vhosts, redirects, health endpoints excluded). Bare
  `cove tunnel up` on a TTY opens an arrow-key picker (termios/cbreak, j/k
  aliases, q/Ctrl-C cancels loud); without a TTY it fails loud listing
  `service — target` lines; unknown shorthand fails loud with the same list.
  (2) Share routing is Cove-rendered: new include `cove-tunnel-shares.conf`
  (mounted in docker-compose, included from `default.conf.j2` after user.d)
  is regenerated from `COVE_TUNNEL_SHARES` state in the compose `.env`
  (share=service pairs), server blocks per `<name>.share.zrok.io` route to the
  service upstream with `Host: $host`, `nginx -t` validates and `nginx -s
  reload` applies (previous file restored on rejection — rollback on failure,
  never silent). `down` releases the share and re-renders the include; bare
  `down` clears all share routes. bringup seeds an empty include (force:false)
  so the bind-mount is never wedged as a directory. zrok2 HTTPS targets now
  pass `--insecure` (self-signed cove certs on the internal hop; relay edge
  terminates public TLS). TDD: failing tests written first for the three new
  discovery/route/state behaviors. Test gate: 511 passed (was 482; +29 tunnel
  rework tests, +2 net). Coverage matrix +4 paths. Plan + tunnel.md updated to
  the reworked UX. Known non-blocker: discovery currently resolves the
  tailscale ts.net vhost to a forgejo route — harmless duplicate entry in the
  picker, candidate for a name-filter follow-up.
- 2026-09-22 (implementation): Token onboarding + rotation. `cove tunnel up` with no
  token anywhere now onboards interactively (TTY): signup pointer, hidden token
  prompt, write to shared 1Password item (op run wrapper; create-if-missing), cache
  in Vault + compose .env. Non-TTY still fails loud. New `cove tunnel reset-token`:
  retires the token, appends it to the Zrok Account item as
  `account_token_previous[password]` (history survives revoked-token overwrite),
  deletes from Vault + compose .env; next `up` re-onboards. 13 new tests (86 total
  tunnel tests); full non-e2e gate 527 passed, 25 deselected. docs/services/tunnel.md
  updated (onboarding + rotation sections).
- 2026-09-22 (implementation): Crash-loop fix. The openziti/zrok2 image entrypoint IS
  `zrok2`, so the compose override `command: ["sleep", "infinity"]` was parsed by zrok2
  as a subcommand → crash loop → `docker compose exec` failed with "container is
  restarting" → surfaced as "zrok2 enable failed:" with empty detail. Fixed by
  overriding the entrypoint directly: `entrypoint: ["/usr/bin/env", "sleep", "infinity"]`
  (no published ports, posture unchanged). Verified live: sidecar Up, `zrok2 status`
  responds. Resource sync + `cove init --force` propagated to the deployed compose dir.
- 2026-09-23 (implementation): `zrok2 enable` now passes `--headless` — the exec
  path has no TTY, so the TUI-enabled enable failed with "open /dev/tty: no such
  device or address". Platform-mismatch warning (linux/amd64 image on arm64 host)
  is cosmetic (Rosetta/QEMU emulated fine — status responded). Gate: 528 passed.
- 2026-09-23 (implementation): Platform-aware image pinning (operator request). The
  zrok2 image is multi-arch (amd64 + arm64 manifests exist); `cove tunnel up` now
  pins per-arch via `TUNNEL_IMAGE` env when bringing up the sidecar —
  `_host_arch()` maps platform.machine() → amd64/arm64 (loud failure on unsupported
  arch), `_tunnel_image()` returns `openziti/zrok2:2.0.4@<per-arch-digest>`
  (amd64 f607c294…, arm64 8864ba64…). Compose default demoted to the multi-arch
  manifest so Docker picks the matching arch (warning disappears on arm64 since the
  arm64 digest is pinned explicitly). 5 new tests (90 tunnel tests). Gate: 532 passed.
- 2026-09-23 (implementation): Root cause of the 401 chain + share-name fix.
  (a) The deployed leaf cert (cove.local.pem, Aug 12) lacked the Authority Key
  Identifier extension — _generate_leaf in cli/cove/certs.py never added AKI/SKI.
  openssl CLI verified OK but python ssl / macOS Security.framework rejected the
  chain ("Missing Authority Key Identifier"), so Vault lookups failed silently →
  _vault_get returned None → fell back to the placeholder ZROK_ACCOUNT_TOKEN=tok
  in the deployed compose .env → zrok.io 401. Fixed at the source (AKI + SKI on
  every generated leaf), re-issued the deployed cert, nginx reloaded; urllib now
  verifies. (b) Cleared the fixture-placeholder token ("tok", "fresh-token") from
  the deployed compose .env, the local op-cache, and the Vault cache.
  (c) Ephemeral public shares no longer pass a client-invented -n token (409
  shareConflict — the name must be reserved first); named shares now run
  `zrok2 create name` first (idempotent). Private shares use server-generated
  tokens unless pre-created via `zrok2 create share private --share-token`.
  Gate: 536 passed.
- 2026-09-23 (implementation): enable idempotency fix. `zrok2 status` exits 0 with
  a Config table even when NOT enabled — the old check ("environment enabled" in
  output) never matched, so enable re-ran and crashed with "you already have an
  enabled environment". Now `_environment_enabled()` requires an Account Token
  `<<SET>>` row in status output, and the enable error path treats "already have
  an enabled environment" as success. Gate: 538 passed.
