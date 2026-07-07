# Sashay: Dagu MVP (Shape 2 — Shared `dagu.cove`, API-Only)

**Branch:** `sashay-dagu-mvp` (off `main`)
**Musing:** `docs/musings/windmill-script-scheduler.md`
**Parley records:** `docs/musings/parleys/2026-07-06-dagu-revision.md`, `docs/musings/parleys/2026-07-06-dagu-essential-use-case.md`
**C4 diagrams:** `docs/musings/parleys/2026-07-06-c4-diagrams.md`
**ADR:** `docs/adr/adr-016-two-tier-service-adoption-rubric.md`

## Scope

Add Dagu, MinIO, and ntfy to the Cove compose stack as platform infrastructure. Cove hosts a shared Dagu instance at `dagu.cove` (Shape 2 MVP). All DAGs are API-only `run:` steps using a `cove-tools` image (Dagu binary + curl + openssl + jq + python3 + mc). MinIO at `s3.cove` / `console.s3.cove`. ntfy at `notify.cove`. Bootstrap credentials in `compose/.env` (existing pattern). No Docker socket access anywhere.

**Out of scope:** `*.apps.cove` routing, per-project `cove-dagu` containers (Shape 1 graduation), keychain migration, example DAGs, health-check DAGs, backup DAGs, cert-renewal DAGs. Those are user workflows or separate sashays.

## Services to add

### 1. cove-tools image

Custom image built from Dagu upstream + tools. Dockerfile in `compose/cove-tools/`:

```dockerfile
FROM dagucloud/dagu:latest
RUN apk add --no-cache curl openssl jq python3
RUN curl -fsSL https://dl.min.io/client/mc/release/linux-amd64/mc -o /usr/local/bin/mc && chmod +x /usr/local/bin/mc
```

Build via compose `build:` directive (not pre-built/pushed to registry — that's a future step when CI exists for it). The image is local-only for MVP.

### 2. Dagu service

- Image: `cove-tools` (built from `compose/cove-tools/`)
- Container name: `cove-dagu`
- Internal port: `8080` (Dagu HTTP server)
- Data: `~/Documents/cove-data/dagu/` (DAGs, run history, logs, queue, persistent state — all file-backed)
- Env: `DAGU_HOST`, `DAGU_PORT`, `DAGU_SECRETS_VAULT_ADDRESS`, `DAGU_SECRETS_VAULT_TOKEN` (from `.env`)
- No Docker socket mounted. No host filesystem mounted (except cove-data/dagu for state).
- Restart: `unless-stopped`
- Memory limit: 512M

### 3. MinIO service

- Image: `minio/minio:latest`
- Container name: `cove-minio`
- Internal ports: `9000` (S3 API), `9001` (console)
- Data: `~/Documents/cove-data/minio/` (objects are real files, caught by machine backups)
- Env: `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD` (from `.env`)
- Command: `server /data --console-address ":9001"`
- Restart: `unless-stopped`
- Memory limit: 512M

### 4. ntfy service

- Image: `binwiederhier/ntfy:latest`
- Container name: `cove-ntfy`
- Internal port: `8080` (ntfy HTTP)
- Data: `~/Documents/cove-data/ntfy/` (cache DB, attachments)
- Command: `serve`
- Restart: `unless-stopped`
- Memory limit: 256M
- Auth: none for MVP (per T13)

## Changes

### A. `compose/cove-tools/Dockerfile` (new)

As above.

### B. `compose/docker-compose.yml`

Add four services: `cove-tools` (build context), `dagu`, `minio`, `ntfy`. Wire volumes, env, restart, memory limits, depends_on (nginx depends on all backend services).

### C. `compose/bringup.yml`

1. **Data directories** — add `dagu/`, `minio/`, `ntfy/` to the "Create cove data directories" loop.
2. **Cert SANs** — add `dagu.cove`, `s3.cove`, `console.s3.cove`, `notify.cove` to the `cove certs sign` argv list.
3. **Cert validation** — add the new hostnames to the validation shell check loop.
4. **/etc/hosts** — add `dagu.cove s3.cove console.s3.cove notify.cove` to the lineinfile line.
5. **Compose .env** — add:
   - `DAGU_CONTAINER_NAME=cove-dagu`
   - `MINIO_CONTAINER_NAME=cove-minio`
   - `NTFY_CONTAINER_NAME=cove-ntfy`
   - `MINIO_ROOT_USER={{ minio_root_user }}`
   - `MINIO_ROOT_PASSWORD={{ minio_root_password }}`
   - `DAGU_SECRETS_VAULT_ADDRESS=https://vault.cove/`
   - `DAGU_SECRETS_VAULT_TOKEN={{ dagu_vault_token }}`
6. **Health wait** — add wait-for blocks for Dagu, MinIO, ntfy (HTTP checks against nginx-routed endpoints).
7. **Print summary** — add Dagu, MinIO, ntfy URLs.

### D. `compose/nginx/default.conf.j2`

Add upstreams and server blocks:
- `upstream dagu_backend { server dagu:8080; }`
- `upstream minio_backend { server minio:9000; }`
- `upstream minio_console_backend { server minio:9001; }`
- `upstream ntfy_backend { server ntfy:8080; }`
- `server_name dagu.cove` → proxy to `dagu_backend`
- `server_name s3.cove` → proxy to `minio_backend`
- `server_name console.s3.cove` → proxy to `minio_console_backend`
- `server_name notify.cove` → proxy to `ntfy_backend`

All with standard SSL (cove.local.pem), proxy headers, and `proxy_set_header Host $host`.

### E. `compose/group_vars/all.yml`

Add defaults:
- `minio_root_user: cove-minio` (default; real value in host_vars or .env)
- `minio_root_password: ""` (must be set — fail if empty)
- `dagu_vault_token: ""` (set after Vault bootstrap; empty for MVP if Dagu Vault integration not wired yet)

### F. `cli/cove/status.py`

Add the three new containers to `SERVICES` list:
- `("cove-dagu", "Dagu")`
- `("cove-minio", "MinIO")`
- `("cove-ntfy", "ntfy")`

Add health check functions:
- `_check_dagu()` — GET `https://127.0.0.1:8443/` with `Host: dagu.cove`, expect 200 (Dagu web UI).
- `_check_minio()` — GET `https://127.0.0.1:8443/minio/health/live` with `Host: s3.cove`, expect 200.
- `_check_ntfy()` — GET `https://127.0.0.1:8443/` with `Host: notify.cove`, expect 200 (or 404 if no root handler — check what ntfy returns).

Wire into `check_all()`.

### G. `cli/cove/resources/`

The compose resources are bundled into the CLI package at build time via `scripts/sync_compose_resources.py`. The new `compose/cove-tools/Dockerfile` and any new compose files must be included in the sync. Check `scripts/sync_compose_resources.py` and ensure the glob covers `compose/cove-tools/**`.

### H. Tests

**Unit tests** (in `cli/tests/`):
- `test_status.py` (extend existing or new) — test that `SERVICES` includes the 3 new containers, test `_check_dagu`/`_check_minio`/`_check_ntfy` mock HTTP responses (200 = ok, connection refused = not ok).
- Test failure cases: missing containers, non-200 responses, timeouts.

**E2E tests** (in `cli/tests/`):
- Extend `test_e2e_dns.py` or add `test_e2e_dagu.py` — verify nginx config routes new hostnames (can use `curl -H "Host: dagu.cove" https://127.0.0.1:8443/` against a running stack). These self-skip if the stack isn't running.

**Failure-expecting test (mandatory):**
- Test that `cove status` reports Dagu/MinIO/ntfy as down when containers are not running.

### I. Documentation

- `README.md` — add Dagu, MinIO, ntfy to the service list and URLs.
- `AGENTS.md` — update Cove-specific notes if needed (new services, ports).
- `docs/architecture.md` — update service topology section.

## Sashay steps

1. Create worktree `.worktrees/sashay-dagu-mvp`, branch off `main`.
2. Write `compose/cove-tools/Dockerfile`.
3. Add services to `compose/docker-compose.yml`.
4. Update `compose/bringup.yml` (data dirs, SANs, .env, health waits, summary).
5. Update `compose/nginx/default.conf.j2` (upstreams + server blocks).
6. Update `compose/group_vars/all.yml` (defaults).
7. Update `cli/cove/status.py` (new containers + health checks).
8. Ensure `scripts/sync_compose_resources.py` covers new files.
9. Write tests (failure-expecting test first, then positive tests).
10. Run full test suite: `uv run --directory cli pytest tests/ -q`.
11. Staging E2E: `cove up` (needs sudo — operator-assisted), verify new services respond, teardown.
12. Code review.
13. Chronicle + PR.

## Notes for the subagent

- The test command is `uv run --directory cli pytest tests/ -q` (run from repo root). E2E tests self-skip if the stack isn't running.
- `cove up` requires sudo. Staging E2E will need operator assistance — flag this in the chronicle when you reach that step and the operator will run it.
- Pin Dagu and MinIO versions rather than `latest` where possible. Check upstream for stable tags. ntfy likewise.
- The `cove-tools` image uses `dagucloud/dagu` — note the Docker Hub / GHCR path. The musing says `ghcr.io/dagucloud/dagu:latest` but the compose snippet references it. Verify the correct image path and pin a version.
- MinIO root credentials must be non-empty. Fail loud (per AGENTS.md) if `minio_root_password` is empty at compose-up time.
- Dagu Vault token can be empty for MVP (Vault integration is optional — DAGs can read secrets via env vars or the HTTP API). Don't fail if `dagu_vault_token` is empty.
- ntfy is authless for MVP. Don't add auth config.