# Jam: Speedtest Tracker unhealthy — missing APP_KEY

Date: 2026-08-13
Desc: `cove status` reports Speedtest "Up 5 hours (unhealthy)". Container halts init with "An application key is missing, halting init!".

## 2026-08-13 — Reproduce: APP_KEY empty in running container

- What: `cove status` → Speedtest unhealthy. `docker logs cove-speedtest-tracker` → "An application key is missing, halting init!". `docker inspect` env shows `APP_KEY=` (empty), `SPEEDTEST_SCHEDULE` set, `APP_URL=https://speedtest.cove.local`.
- Result: Container is up but never initialized — Laravel can't boot without APP_KEY.
- Next: Find why APP_KEY is empty. The shared 1Password item "Speedtest Tracker" (keyed to speedtest.cove.local) exists with a valid `base64:` key. `cove creds vault-get op://Private/Speedtest Tracker/app_key` → "not cached. Run `cove creds batch-pull` first."
- Hypothesis: `_ensure_app_key()` (runs on `cove speedtest up`) never ran, OR the compose `.env` was never written, OR bringup.yml started the container with empty default before provisioning.

## 2026-08-13 — Root cause: two bugs

- **Bug A (unhealthy container):** `compose/.env` has `SPEEDTEST_APP_KEY=` (empty). `bringup.yml` re-renders `.env` **unconditionally** (no `when: not exists`) with `SPEEDTEST_APP_KEY={{ speedtest_app_key | default('') }}`. `speedtest_app_key` is never defined anywhere → every `cove up` clobbers the key that `cove speedtest up` wrote. Container restarts with empty `APP_KEY` → Laravel halts init → unhealthy.
- **Bug B (cove speedtest up fails):** `_inject_admin_env()` requires the shared `Cove Admin` item cached in Vault/local cache. But `cove creds batch-pull`'s `OP_REFS` only covers forgejo/vault/minio — NOT `Cove Admin`. So on a fresh machine `cove speedtest up` always fails with "Speedtest Tracker admin identity is missing". The 1Password items exist (`op item get "Cove Admin"` works) but aren't pulled by batch-pull.
- Verified: `cove creds vault-get op://Private/Speedtest Tracker/app_key` → returns key (cached). `cove creds vault-get op://Private/Cove Admin/username` → "not cached". `cove speedtest up` → fails on admin identity.
- Next: write failing tests for both bugs, then fix.

## 2026-08-13 — Fix applied (TDD)

- **Bug A fix:** `compose/bringup.yml` `.env` render is now `when: not (compose_dir ~ "/.env") is exists` (first boot only), matching the plan (line 155) and the litellm `config.yaml` precedent. A subsequent `cove up` no longer clobbers the CLI-provisioned `SPEEDTEST_APP_KEY`.
- **Bug B fix:** `cli/cove/creds.py` `OP_REFS` now includes the shared `Cove Admin` (username/password) and `Speedtest Tracker` (app_key) items, so `cove creds batch-pull` caches them and `cove speedtest up` can resolve the admin identity + APP_KEY on a fresh machine.
- Tests: added `test_bringup_env_render_is_first_boot_only`, `test_bringup_env_does_not_hardcode_empty_app_key`, `test_batch_pull_includes_cove_admin`, `test_batch_pull_includes_speedtest_app_key`. All red before fix, green after. Full suite: 356 passed.
- Next: reinstall cove wheel (compose change requires reinstall), then `cove speedtest up` + `cove up` to heal the container.
