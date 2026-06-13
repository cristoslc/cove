# Plan: Nginx as Sole Ingress — No Direct Port Publishing

**Based on:** `docs/musings/nginx-as-sole-ingress.md`, `docs/adr/adr-014-nginx-as-sole-ingress.md`
**Trove:** `reverse-proxy-alternatives@b1e3e2e`
**Date:** 2026-06-11

## Goal

Remove all host port publishing from forgejo and vault. Route all HTTP traffic through nginx at `*.cove` subdomains. Only SSH (2222) and dnsmasq (5353) keep host ports.

**Future:** nginx's `stream` module can proxy SSH through the ingress controller (`git@git.cove` → forgejo:22), eliminating the separate SSH port mapping. Deferred to a follow-up spec — not in this plan's scope.

## Changes

### 1. docker-compose.yml

- [ ] Remove forgejo HTTP port mapping (`127.0.0.1:3000:3000`). Keep SSH (`127.0.0.1:2222:22`).
- [ ] Remove vault port mapping (`127.0.0.1:8200:8200`).
- [ ] Add `vault` to nginx `depends_on` (condition: service_started).
- [ ] Change vault `VAULT_ADDR` env to `https://vault.cove/` (for CLI consumption).

### 2. group_vars/all.yml

- [ ] `forgejo_domain`: `localhost` → `git.cove`
- [ ] `forgejo_root_url`: `http://localhost:3000/` → `https://git.cove/`
- [ ] `forgejo_ssh_domain`: `localhost` → `git.cove`
- [ ] `vault_addr`: `http://127.0.0.1:8200` → `https://vault.cove/`
- [ ] Remove `forgejo_http_bind` (no longer needed).
- [ ] Remove `vault_bind` (no longer needed).

### 3. bringup.yml

- [ ] Set `forgejo_root_url` fact to `https://git.cove/`.
- [ ] Set `forgejo_domain` fact to `git.cove`.
- [ ] Set `cove_domain` fact to `cove`.
- [ ] Update `.env` template: `FORGEJO_DOMAIN=git.cove`, `FORGEJO_ROOT_URL=https://git.cove/`, `FORGEJO_SSH_DOMAIN=git.cove`. Drop `FORGEJO_HTTP_BIND` and `VAULT_BIND`.
- [ ] Change forgejo health check URL to `https://git.cove/api/healthz` (through nginx).
- [ ] Change vault health check URL to `https://vault.cove/v1/sys/health` (through nginx).
- [ ] Update mkcert cert to include `cove`, `*.cove`, `git.cove`, `vault.cove`.
- [ ] Update `/etc/hosts` to include `cove git.cove vault.cove cove.local`.
- [ ] Update summary to show `https://git.cove/` and `https://vault.cove/`.

### 4. nginx/default.conf.j2

- [ ] Add `upstream vault_backend { server vault:8200; }`.
- [ ] Add `git.cove` server block (forgejo proxy).
- [ ] Add `vault.cove` server block (vault proxy).
- [ ] Add `*.pages.cove` server block (pages hosting).
- [ ] Keep `cove.local` server block (legacy, forgejo proxy).
- [ ] Keep tailscale FQDN server block (conditional on `ts_dns_name`).

### 5. provision_forgejo.yml

- [ ] No changes needed — already uses `forgejo_root_url` from group_vars which will be `https://git.cove/`. All `uri` tasks have `validate_certs: false`.

### 6. bootstrap_vault.yml + provision_vault_user.yml

- [ ] No changes needed — already uses `vault_addr` from group_vars which will be `https://vault.cove/`. All `uri` tasks have `validate_certs: false`.

### 7. provision_pages.yml

- [ ] Update fallback URL from `https://cove.local:8443/` to `https://git.cove/`.
- [ ] Update fallback `forgejo_root_url` set_fact to `https://git.cove/`.

### 8. cli/cove/project.py

- [ ] `_render_context`: `vault_addr` now reads `VAULT_ADDR` from container env (which will be `https://vault.cove/`).
- [ ] `_render_agents_block`: forgejo URL → `https://git.cove/`, vault URL → `https://vault.cove/`.

### 9. cli/cove/templates/detail-cove.md.j2

- [ ] Forgejo web URL: `https://git.cove/`.
- [ ] Vault address: `https://vault.cove/`.
- [ ] Architecture table: update nginx port to 443, forgejo external to `https://git.cove/`, vault external to `https://vault.cove/`.

### 10. cli/cove/templates/project-guidance.md.j2

- [ ] Forgejo URL: `https://git.cove/`.
- [ ] Vault URL: `https://vault.cove/`.

### 11. Tests

- [ ] Update test assertions for new URLs.
- [ ] Update `_render_context` test expectations.
- [ ] Update `_render_agents_block` test expectations.

## Verification

1. `cove up` succeeds — all health checks pass through nginx.
2. `cove creds vault-get` works — CLI reaches vault through nginx.
3. `https://git.cove/` loads Forgejo in browser.
4. `https://vault.cove/` loads Vault UI in browser.
5. `git push` to `forgejo-localhost` works (SSH on 2222).
6. All 67 tests pass.
