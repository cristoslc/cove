# Musing: Nginx as Sole Ingress — No Direct Port Publishing

**Date:** 2026-06-11
**Context:** Refactoring Cove's service exposure model after removing tailscale serve and adopting `*.cove` subdomains with mkcert TLS.
**Resolved by:** ADR-014: Nginx as Sole Ingress Controller
**Trove:** `reverse-proxy-alternatives@b1e3e2e`

## Intent

All Cove services (forgejo, vault, pages) are accessible **only** through nginx as the ingress controller. No service publishes a host port directly — not even on `127.0.0.1`. The only exception is SSH (port 2222), which cannot be proxied through nginx.

User-facing URLs use `*.cove` subdomains resolved via `/etc/hosts`:

| Service  | URL                     | Backend         |
|----------|-------------------------|-----------------|
| Forgejo  | `https://git.cove/`     | forgejo:3000    |
| Vault    | `https://vault.cove/`   | vault:8200      |
| Pages    | `https://*.pages.cove/` | /data/pages/sites |

mkcert generates a wildcard cert for `*.cove` (plus `*.cove.local` for legacy). nginx terminates TLS on `127.0.0.1:443`. Tailscale serve forwards `:443` → `127.0.0.1:443` for remote access.

## Implications

### 1. Forgejo HTTP port (3000) — removed from host

Forgejo's HTTP port is no longer published. All HTTP traffic to forgejo goes through nginx. The compose file keeps only the SSH port mapping (`127.0.0.1:2222:22`).

**Knock-on:** Ansible health checks and provision playbook API calls must go through nginx at `https://git.cove/`. The `forgejo_root_url` variable changes from `http://localhost:3000/` to `https://git.cove/`. The `validate_certs: false` flag on all `uri` tasks handles the mkcert CA trust during provisioning.

### 2. Vault port (8200) — removed from host

Vault's port is no longer published. All traffic to vault goes through nginx at `https://vault.cove/`.

**Knock-on:** The `cove creds` CLI reads `VAULT_ADDR` from the container environment. Currently this is `http://127.0.0.1:8200`. It must change to `https://vault.cove/` so the CLI routes through nginx. Vault's internal API binding (`VAULT_API_ADDR`) stays at `http://127.0.0.1:8200` — that is container-internal and unaffected.

The vault healthcheck in docker-compose (`vault status -address=http://127.0.0.1:8200`) is container-internal and unaffected.

### 3. Ansible health checks — route through nginx

The bringup playbook currently waits for forgejo at `http://localhost:3000/api/healthz` and vault at `http://127.0.0.1:8200/v1/sys/health`. With no host ports, these must go through nginx:

- Forgejo: `https://git.cove/api/healthz` (nginx → forgejo:3000)
- Vault: `https://vault.cove/v1/sys/health` (nginx → vault:8200)

nginx depends on both forgejo and vault being started (`depends_on` with `condition: service_started`). The health check runs after `docker compose up`, so nginx is already running.

### 4. Provision playbook — route through nginx

The provision_forgejo.yml playbook uses `forgejo_root_url` for:
- Install POST (sets ROOT_URL in Forgejo config)
- Post-install health check (`api/v1/version`)
- API calls (create repo, register SSH key, etc.)

All of these go through nginx at `https://git.cove/`. The install POST is the only one that needs special attention — Forgejo in install mode serves on port 3000, and nginx proxies to it. This should work transparently.

### 5. Bootstrap vault — route through nginx

The bootstrap_vault.yml and provision_vault_user.yml playbooks use `vault_addr` for:
- Health check (`/v1/sys/health`)
- Init POST (`/v1/sys/init`)
- Unseal PUT (`/v1/sys/unseal`)
- User creation

All go through nginx at `https://vault.cove/`. Vault's API works through a reverse proxy — nginx just forwards the HTTP traffic.

### 6. `cove creds` CLI — route through nginx

The CLI reads `VAULT_ADDR` from the container environment via `docker inspect`. Currently `VAULT_ADDR=http://127.0.0.1:8200`. Changing it to `VAULT_ADDR=https://vault.cove/` makes the CLI route through nginx.

The CLI uses Python's `urllib` which trusts the system CA store. mkcert installs its CA system-wide, so TLS verification should pass.

**Risk:** If nginx is down (e.g., `cove down` was run but vault container is still up), the CLI cannot reach vault. This is acceptable — the CLI is an admin tool that expects the full stack to be running.

### 7. Nginx template — new server blocks

The nginx config needs server blocks for:
- `git.cove` → forgejo:3000 (primary forgejo endpoint)
- `cove` → forgejo:3000 (bare domain convenience)
- `vault.cove` → vault:8200 (vault UI and API)
- `*.pages.cove` → /data/pages/sites (pages hosting)
- `cove.local` → forgejo:3000 (legacy, keep for transition)
- Tailscale FQDN → forgejo:3000 (if tailscale is up, with tailscale cert)

### 8. Group vars and .env — updated defaults

| Variable | Old | New |
|----------|-----|-----|
| `forgejo_domain` | `localhost` | `git.cove` |
| `forgejo_root_url` | `http://localhost:3000/` | `https://git.cove/` |
| `forgejo_ssh_domain` | `localhost` | `git.cove` |
| `forgejo_http_bind` | `127.0.0.1` | *removed* |
| `vault_addr` | `http://127.0.0.1:8200` | `https://vault.cove/` |
| `vault_bind` | `127.0.0.1` | *removed* |

The `.env` file rendered by bringup.yml drops `FORGEJO_HTTP_BIND` and `VAULT_BIND`. `FORGEJO_ROOT_URL` becomes `https://git.cove/`. `FORGEJO_DOMAIN` becomes `git.cove`.

### 9. Project guidance and hub — updated URLs

The `cove install` guidance (both hub block and detail spoke) must show:
- Forgejo: `https://git.cove/`
- Vault: `https://vault.cove/`

The `_render_context` function in `project.py` reads `VAULT_ADDR` from the container env. With the new `VAULT_ADDR=https://vault.cove/`, the rendered guidance will be correct.

### 10. SSH — unchanged

SSH on `127.0.0.1:2222` stays. nginx cannot proxy SSH traffic. The `forgejo-localhost` SSH config alias handles routing.

### 11. dnsmasq — unchanged

dnsmasq on `127.0.0.1:5353` stays. It provides offline wildcard DNS for pages subdomains. Not user-facing HTTP, so the "no direct publishing" rule doesn't apply.

## Open Questions

1. **Vault CLI without nginx:** If someone runs `cove creds vault-get` while nginx is down, it will fail. Is this acceptable? The CLI is an admin tool — it expects the stack to be running. Yes, acceptable.

2. **Provision ordering:** The provision playbook runs after bringup succeeds. nginx is up by then. The install POST goes through nginx to forgejo:3000. This should work — forgejo in install mode serves on port 3000, and nginx proxies to it.

3. **mkcert CA trust for Ansible:** Ansible's `uri` module uses Python's `urllib`. mkcert installs its CA system-wide. `validate_certs: false` is already set on all tasks, so this is a non-issue for provisioning. For the CLI, Python's `urllib` should trust the mkcert CA automatically.

4. **Vault internal healthcheck:** The compose healthcheck uses `vault status -address=http://127.0.0.1:8200` inside the container. This is unaffected — it's container-internal.

5. **Pages provisioning:** The provision_pages.yml playbook uses `forgejo_root_url` for API calls. With `forgejo_root_url=https://git.cove/`, these go through nginx. The fallback check also uses nginx. Should work.

## Decision

Proceed with removing all host port publishing (except SSH and dnsmasq). Route all HTTP traffic through nginx. Update all URLs, health checks, and CLI configuration to use `*.cove` subdomains.
