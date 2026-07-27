# Jam: `cove creds vault-get` not working via vault.cove

## 2026-07-26 — Reproduction & root cause

- **Symptom:** `cove creds vault-get 'op://Private/test/password'` → `ConnectionRefusedError: [Errno 61] Connection refused`
- **Repro:** Confirmed. The CLI's `vault_cache._vault_request` POSTs/GETs to `_vault_addr()` which defaults to `http://127.0.0.1:8200`.
- **Root cause:** `compose/docker-compose.yml:101` defines the `vault` service with **no `ports:` mapping**. Port 8200 is not published to the host. Vault is only reachable via the nginx ingress at `https://vault.cove/` (verified: `/v1/sys/health` returns 200 through `curl -H "Host: vault.cove" https://127.0.0.1/`).
- **Affected modules:**
  - `cli/cove/vault_cache.py:15` — `VAULT_ADDR_DEFAULT = "http://127.0.0.1:8200"`
  - `cli/cove/vault_unseal.py:11` — `VAULT_ADDR_DEFAULT = "http://127.0.0.1:8200"`
- **Decision (operator):** Point the CLI at `https://vault.cove/` with cove CA cert for TLS verification. No compose change.

## Context facts

- cove root CA: `~/.config/cove/pki/rootCA.pem` (exposed via `cove.certs.ca_path()` and `cove.certs.root_ca_pem()`)
- nginx serves `vault.cove` on host port 8443 (published), 8080 for HTTP
- `status.py:_check_vault` already hits `https://127.0.0.1:8443/v1/sys/health` with `Host: vault.cove` header and `verify=False` (uses `requests`)
- `vault_cache` and `vault_unseal` use stdlib `urllib.request`, not `requests`

## Resolution (2026-07-26)

- **Fix:** Changed `VAULT_ADDR_DEFAULT` to `https://vault.cove/` in both
  `vault_cache.py` and `vault_unseal.py`. Added `_vault_ssl_context()` that
  builds an `ssl.SSLContext` loading the cove root CA from
  `~/.config/cove/pki/rootCA.pem` (via `cove.certs.ca_path()`). Passed the
  context to every `urllib.request.urlopen` call in both modules.
- **Tests:** 7 new tests across `test_vault_cache.py` and `test_vault_unseal.py`
  covering: default addr, env override, env unset fallback, SSL context loads
  CA + CERT_REQUIRED, urlopen receives context. All RED before fix, GREEN after.
- **Live verification:** `cove creds vault-put` then `cove creds vault-get` on a
  real 1Password item round-trips cleanly over `https://vault.cove/` with TLS
  verification. Original `ConnectionRefusedError` gone.
- **Suite:** No new failures. 9-10 pre-existing LiteLLM test failures logged to
  `docs/tech-debt/litellm-test-drift.md` (config drift, unrelated to vault).
- **Commit:** `f8825b9` on `main`.