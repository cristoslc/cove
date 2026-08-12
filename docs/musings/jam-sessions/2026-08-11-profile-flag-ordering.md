# Jam Session: `--profile` flag ordering breaks `cove speedtest up`

Started: 2026-08-11

## Context

Operator-assisted E2E surfaced a bug: `docker compose up -d --profile speedtest`
fails with `unknown flag: --profile` on Docker Compose 5.4.0. `--profile` is a
**global** compose flag and must precede the `up` subcommand. Both
`cli/cove/speedtest.py` and the pre-existing `cli/cove/litellm.py` pass it
AFTER `up`, so `cove speedtest up` (and `cove litellm up`) are broken.

## Log

### 2026-08-11 17:20 — Reproduced
- `docker compose up -d --profile speedtest` → `unknown flag: --profile`
- `docker compose --profile speedtest up -d` → works (correct ordering)
- Confirmed: `--profile` must precede `up` in Docker Compose 5.4.0.
- litellm.py uses identical wrong ordering (`up -d --profile litellm`).

### 2026-08-11 17:2x — RED test written
- `test_speedtest_up_profile_before_subcommand` asserts `--profile` precedes `up` in the compose argv.
- Fails against current code: `['docker','compose','--project-directory',...,'up','-d','--profile','speedtest']` — `--profile` (idx 6) after `up` (idx 4).
- Root cause isolated: `--profile` is a GLOBAL compose flag, must precede the subcommand. `litellm.py` has the same bug.

### 2026-08-11 17:24 — GREEN
- Fix: moved `--profile <name>` to precede `up` in `_compose_cmd` call:
  - speedtest.py: `_compose_cmd("--profile", "speedtest", "up", "-d")`
  - litellm.py: `_compose_cmd("--profile", "litellm", "up", "-d")`
- Both new tests pass. `docker compose --profile speedtest up -d` no longer errors with `unknown flag`.
- (Pull failed only due to missing docker-credential-desktop in PATH — unrelated env issue.)

### 2026-08-11 17:4x — ROOT CAUSE: double-slash Vault URL
- `cove speedtest up` auto-gen fails: `Vault write failed ... HTTP 404`.
- Isolated: `vault_cache.py` `_vault_addr()` returns `https://vault.cove.local/` (trailing slash) and `_vault_request` does `f"{_vault_addr()}/v1/{path}"` → `https://vault.cove.local//v1/...` (DOUBLE SLASH).
- Vault returns 404 for the double-slash path (confirmed via urllib: single-slash=200, double-slash=404).
- Pre-existing bug in `vault_cache.py`, blocks the auto-gen feature.

### 2026-08-11 23:0x — ROOT CAUSE #2: APP_KEY format
- After fixing double-slash, auto-gen wrote a raw 64-char APP_KEY.
- Speedtest Tracker (Laravel) requires `base64:<32-byte base64>` format; raw key → 500 "Unsupported cipher or incorrect key length".
- Fix: auto-gen must produce `base64:$(openssl rand -base64 32)` (or `base64:` + token_urlsafe(32)).

### 2026-08-11 23:1x — GREEN
- Added `_generate_app_key()` → `base64:` + b64encode(secrets.token_bytes(32)).
- `_render_seed` replaces `{{generate:64}}` with the base64-prefixed key.
- New test `test_generated_app_key_has_base64_prefix` (RED first). Full suite: 337 passed.
- Also fixed `vault_cache.py` + `vault_unseal.py` double-slash URL (rstrip('/')).
