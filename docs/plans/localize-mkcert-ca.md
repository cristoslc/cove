# Plan: Localize mkcert CA — Eliminate $MKCERT_CAROOT Dependency

**Date:** 2026-06-19
**Musing:** `docs/musings/localize-mkcert-ca.md`

## Summary

Copy `rootCA.pem` into the compose directory at deploy time so docker-compose.yml mounts via a relative path instead of `$MKCERT_CAROOT` (an absolute system path outside `~/Documents/`).

## Changes

1. **`compose/docker-compose.yml`** — change cert mount to `./certs/rootCA.pem`
2. **`compose/bringup.yml`** — add task to copy read rootCA.pem to `{{ compose_dir }}/certs/rootCA.pem`
3. **`compose/.env.example`** — drop `MKCERT_CAROOT` line (it's no longer referenced)
4. **`cli/cove/resources/compose/`** — sync the same 3 changes to the bundled resource copy so `cove init` gets them

## Verification

1. `cove up --no-provision` — should render `.env` without MKCERT_CAROOT and bring up all 5 containers healthy
2. `curl -sk https://git.cove/api/healthz` — returns 200
3. After merge: `scripts/staging/deploy.sh` then `scripts/staging/e2e.sh`