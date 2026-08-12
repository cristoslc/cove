# Plan: Speedtest Tracker for operator internet-link monitoring

> **Source:** `docs/musings/internet-link-monitoring-speedtest-tracker.md`
>
> **Status:** Plan — under sashay. This adds Speedtest Tracker as an optional Cove service monitoring the operator's WAN link (uptime/latency/bandwidth). It does **not** monitor Cove's own services — that stays with OpenObserve (per the observability musing). This plan is intentionally a **small, single-service** addition mirroring the litellm profile pattern.

## Context

The operator wants to monitor their **internet connection** — uptime, latency, and bandwidth of the machine's WAN link. Research settled on **Speedtest Tracker** (`alexjustesen/speedtest-tracker`) as the single tool that natively covers all three axes (download/upload, ping/latency, jitter, packet loss) in one container, using scheduled Ookla `speedtest` CLI runs.

This is deliberately **not** about monitoring Cove's own services. Cove service availability is handled by **OpenObserve** via a blackbox prober → OTLP, per `docs/musings/observability-prometheus-otel.md`. Speedtest Tracker is a **separate, single-purpose, operator-facing** service for the WAN link — cheap (one container, zero external deps when using SQLite), avoids overlap with OpenObserve, and does not duplicate a Prometheus/Grafana stack.

**Fits Cove's litellm pattern:** this is an optional, operator-initiated service. It runs behind the nginx ingress (`speedtest.cove`) like litellm, is controlled via a `cove speedtest` CLI group mirroring `cove litellm`, and uses the `litellm` profile pattern — an **optional profile**, not always-on.

## Scope

Add **Speedtest Tracker** to the Cove stack as an optional profiled service (`profile: speedtest`):

- **Compose service** — `speedtest-tracker` with `profiles: ["speedtest"]`, version-pinned image, SQLite backend (single container, no external DB), data under `${COVE_DATA_ROOT}/speedtest/`, healthcheck, memory limit, non-root, `restart: unless-stopped`.
- **Nginx ingress** — `speedtest.cove` server block (deferred-DNS variable + resolver, mirroring litellm, so nginx starts even when the service is absent).
- **CLI group** — `cove speedtest up/down/status/logs` mirroring `cove litellm`.
- **Landing page** — `speedtest.cove` card + status dot (mirroring litellm).
- **Status** — Speedtest Tracker added to `OPTIONAL_SERVICES` in `cli/cove/status.py`.
- **bringup.yml** — cert SANs + `/etc/hosts` + `.env` for `speedtest.cove`/`speedtest.cove.local`; create `${COVE_DATA_ROOT}/speedtest/`; render `config`/`.env` from template on first boot.
- **Docs** — `docs/speedtest.md`, README Services table, PURPOSE.md service enumeration.
- **Bundled resources** — sync `compose/` → `cli/cove/resources/compose/` (drift test guards).

**Out of scope (boundaries):**
- Cove-service monitoring (stays with OpenObserve).
- Public status page for the WAN link (operator-facing only).
- Notifications wiring (webhook/apprise → ntfy) deferred — the dashboard is the MVP endpoint. See Deferred.

## Behavior Contracts (BDD — drive test design)

### FC-1: `cove speedtest` lifecycle
```
Feature: Speedtest lifecycle
  Scenario: up starts the profiled service
    Given the cove CLI is installed
    When I run `cove speedtest up`
    Then the speedtest-tracker container starts
    And the command exits 0
    And speedtest.cove resolves to the Speedtest Tracker UI

  Scenario: down stops the service (data preserved)
    When I run `cove speedtest down`
    Then the container stops
    And the data directory is preserved

  Scenario: status reports health
    When I run `cove speedtest status`
    Then it reports the running state of the container
```

### FC-2: Ingress routing + isolation
```
Feature: Ingress isolation
  Scenario: speedtest.cove routes to the tracker
    Given nginx is the sole ingress
    When a request arrives for Host: speedtest.cove
    Then it proxies to the speedtest-tracker
    And the tracker binds to 127.0.0.1 only (no published host port on 0.0.0.0)

  Scenario: missing service does not break nginx
    Given the speedtest containers are down
    When nginx starts
    Then it still starts (deferred-DNS variable + resolver)
```

### FC-3: `cove speedtest` CLI shape
```
Feature: CLI
  Scenario: group exposes lifecycle subcommands
    Then the speedtest group has up, down, status, logs
  Scenario: up uses the speedtest profile
    Then `cove speedtest up` uses --profile speedtest
  Scenario: down uses stop, not down
    Then `cove speedtest down` uses the stop command (avoids stopping core services)
  Scenario: status checks through nginx
    Then `cove speedtest status` checks speedtest.cove via 8443, not a direct port
```

### FC-4: Docs reflect the new service
```
Feature: Documentation
  Scenario: service is documented
    Then PURPOSE.md lists speedtest
    And README Services table lists the speedtest row
    And a docs/speedtest.md guide exists
```

## Test Plan (pre-implementation, red-green-refactor)

New test file: `cli/tests/test_speedtest.py` (mirrors `test_litellm.py` structure).

### Tier 0 — unit/config (always run, `-m "not e2e and not staging"`)
Written FIRST (red), before any implementation:
- **T0-1** `test_speedtest_service_exists` — compose defines `speedtest-tracker` (FC-1).
- **T0-2** `test_speedtest_has_profile` — service has `profiles: ["speedtest"]` (FC-1).
- **T0-3** `test_speedtest_binds_localhost_only` — no `0.0.0.0` host port; binds `127.0.0.1` only (FC-2).
- **T0-4** `test_speedtest_has_healthcheck` — service has a healthcheck (FC-1).
- **T0-5** `test_speedtest_has_memory_limit` — memory limit present (FC-1/security).
- **T0-6** `test_speedtest_uses_sqlite` — `DB_CONNECTION=sqlite`, no external DB dependency (single-container footprint).
- **T0-7** `test_speedtest_image_pinned` — image is version-pinned, NOT `:latest` (security).
- **T0-8** `test_speedtest_app_key_env` — `APP_KEY` required via env var, no weak literal default; `up`/bringup fails loud if unset (security).
- **T0-9** `test_speedtest_container_name_cove_prefix` — `container_name` defaults to `cove-speedtest-tracker` (FC-1).
- **T0-10** `test_nginx_renders_speedtest_block` — rendered `default.conf.j2` contains a `speedtest.cove` server block using a deferred-DNS variable + resolver (FC-2).
- **T0-11** `test_nginx_uses_deferred_dns` — the block uses `resolver 127.0.0.11` and `$speedtest_upstream`, so nginx starts without the service (FC-2).
- **T0-12** `test_cli_speedtest_subcommands` — CLI module exposes `up/down/status/logs` (FC-3).
- **T0-13** `test_cli_speedtest_group_registered` — `speedtest` registered in `cli.py` (FC-3).
- **T0-14** `test_speedtest_up_uses_profile_flag` — source uses `--profile speedtest` (FC-3).
- **T0-15** `test_speedtest_down_uses_stop` — source uses `stop` not `down` (FC-3).
- **T0-16** `test_speedtest_status_checks_through_nginx` — source checks `speedtest.cove` via 8443 (FC-3).
- **T0-17** `test_bringup_sans_include_speedtest` — bringup.yml cert SANs include `speedtest.cove`/`speedtest.cove.local` (FC-2).
- **T0-18** `test_bringup_hosts_include_speedtest` — `/etc/hosts` task includes `speedtest.cove` (FC-2).
- **T0-19** `test_bringup_env_includes_speedtest` — `.env` includes `SPEEDTEST_*` vars (FC-2).
- **T0-20** `test_bringup_creates_data_dir` — bringup creates `${COVE_DATA_ROOT}/speedtest/` (FC-1).
- **T0-21** `test_landing_page_has_speedtest` — landing.html has a `speedtest.cove` card + status dot (FC-4).
- **T0-22** `test_optional_services_include_speedtest` — `status.py` OPTIONAL_SERVICES includes Speedtest (FC-4).
- **T0-23 (resources drift)** `test_resources_tree_in_sync` — SHA-256 of `compose/` (speedtest additions) equals `cli/cove/resources/compose/` (security/integrity).
- **T0-24 (inverse)** `test_wrong_host_does_not_route_to_speedtest` — a non-cove Host header does NOT route to the tracker (adversarial, FC-2).
- **T0-25 (inverse)** `test_speedtest_not_in_required_services` — Speedtest is NOT in required `SERVICES` (it's optional) (FC-1).
- **T0-26 (auth posture)** `test_auth_posture_documented` — `docs/speedtest.md` states the auth posture (app login enforced OR nginx basic-auth fallback), so an unauthenticated dashboard can't silently regress (security, adversarial).
- **T0-27 (APP_KEY auto-gen)** `test_app_key_autogen` — `cove speedtest up` auto-generates `SPEEDTEST_APP_KEY` when absent (writes to 1Password + Vault + `.env`), and reuses the cached value on subsequent runs (idempotent). No manual key-setting required (FC-1, security).

### Tier 1 — integration E2E (live stack, `-m e2e and not staging`)
- **T1-1** `test_speedtest_up_starts_container` — `cove speedtest up` starts the container (FC-1).
- **T1-2** `test_speedtest_ui_returns_200` — `speedtest.cove` serves the UI (FC-2).
- **T1-3** `test_speedtest_requires_auth` — unauthenticated/bare `speedtest.cove` reachable through nginx (FC-2; auth is the app's own login, see Security).

### Coverage matrix self-heal
Add `docs/test-coverage-matrix.yaml` paths for: `cove speedtest up/down/status`, `speedtest.cove` ingress, and the `speedtest-tracker` compose definition — with `blast_radius` and Happy/Sad/Edge/Corner cells per the litellm precedent.

## Implementation (post-red tests)

### 1. Compose — `compose/docker-compose.yml`
Add one service (optional profile, mirroring litellm hardening):
- **speedtest-tracker**: `ghcr.io/alexjustesen/speedtest-tracker:<pinned>` (version-pinned, no `latest`), `profiles: ["speedtest"]`, `container_name: cove-speedtest-tracker`, `restart: unless-stopped`, `healthcheck`, memory limit, non-root. Binds `127.0.0.1:${SPEEDTEST_PORT:-8982}:80` — **no `0.0.0.0`**. SQLite backend (`DB_CONNECTION=sqlite`), data volume `${COVE_DATA_ROOT}/speedtest:/config`. Required env: `APP_KEY` (no weak default, fail loud if unset), `APP_URL` (`https://speedtest.cove.local`). Optional: `SPEEDTEST_SCHEDULE`, `SPEEDTEST_SERVERS`, `TZ`, `PRUNE_RESULTS_OLDER_THAN`.

### 2. Nginx — `compose/nginx/default.conf.j2`
Add a `speedtest.cove` server block mirroring the litellm block: deferred-DNS `set $speedtest_upstream http://speedtest-tracker:80;` + `resolver 127.0.0.11`, so nginx starts even when the service is down. Proxy all paths (isolation is the 127.0.0.1 port binding + app login auth, matching the litellm admin-UI posture). Update both `.j2` and the rendered `default.conf`.

### 3. CLI — `cli/cove/speedtest.py`
Mirror `litellm.py`: `up/down/status/logs` against the `speedtest-tracker` service. `up` uses `--profile speedtest`; `down` uses `stop` (avoid stopping core services); `status` checks `speedtest.cove` through nginx on 8443. Register `app.add_command(speedtest)` in `cli/cove/cli.py`.

**`up` auto-generates `APP_KEY`:** on first run, if `SPEEDTEST_APP_KEY` is not already cached, generate a random key (e.g. `secrets.token_urlsafe(32)` or `openssl rand -base64 32`), write it to 1Password via a seed file + `cove creds 1p-bulk-write --execute`, cache it in Vault via `cove creds vault-put`, and inject it into the compose `.env` (idempotent). Subsequent runs read the cached value. Mirror the forgejo/minio credential provisioning pattern (`compose/seeds/*.yaml` + `cove creds`).

### 4. Status — `cli/cove/status.py`
Add `("cove-speedtest-tracker", "Speedtest")` to `OPTIONAL_SERVICES` (not `SERVICES`).

### 5. Landing page — `compose/nginx/landing.html`
Add a `speedtest.cove` card + `dot-speedtest` status entry to the `services` array (mirror litellm).

### 6. bringup.yml
Add `speedtest.cove`/`speedtest.cove.local` to cert SANs, `/etc/hosts`, cert validation, `.env` (`SPEEDTEST_IMAGE`, `SPEEDTEST_PORT`, `SPEEDTEST_CONTAINER_NAME`, `SPEEDTEST_APP_KEY`). Create `${COVE_DATA_ROOT}/speedtest/`. Render `config`/`.env` from template on first boot (conditional `when: not exists`), mirroring litellm's `config.yaml.j2` pattern. `SPEEDTEST_APP_KEY` in `.env` is populated by the CLI auto-gen flow (not a static default).

### 7. Bundled resources
Run `cli/scripts/sync_compose_resources.py` to copy the new compose files into `cli/cove/resources/compose/`.

### 8. Docs
- `docs/speedtest.md` (FC-4 contract): what it monitors, FQDN, auth, `cove speedtest` usage.
- README Services table → `speedtest.cove` row.
- PURPOSE.md service enumeration → add speedtest.

## Security posture

- **No published `0.0.0.0` host port** — binds `127.0.0.1` only (mirror litellm); reachable only through nginx (sole ingress, ADR-014). nginx publishes `0.0.0.0:8443`, so `speedtest.cove` is LAN/Tailscale-reachable → auth is required, not cosmetic.
- **Access gate is the app's own login — posture must be verified against the pinned version.** Speedtest Tracker historically shipped **unauthenticated by default** on early versions; recent versions added user auth. The implementer MUST verify the pinned image's auth posture at `speedtest.cove` and confirm login is enforced (mirroring the litellm admin-UI-with-master-key gate). Because `speedtest.cove` is LAN/Tailscale-reachable, an unauthenticated-by-default image is NOT acceptable without an explicit mitigation (enable auth on first boot, or layer nginx basic-auth).
- **Low sensitivity accepted only when auth is enforced** — the payload is WAN speed metrics (no credentials, no secrets), so app-login-only is acceptable; but it must be a real login, not a silent unauthenticated dashboard. If the pinned version cannot enforce login, fall back to nginx basic-auth at the `speedtest.cove` block (documented in `docs/speedtest.md`).
- **`APP_KEY` + admin credentials auto-generated and stored in 1Password + Vault, keyed by the `speedtest.cove.local` URL** — a **single shared 1Password item** (title `Speedtest Tracker`, URL `https://speedtest.cove.local/`) holds the admin username, admin password, and APP_KEY. This item is **shared across all the operator's machines** (not per-hostname), so the same credentials work everywhere. On first `cove speedtest up`, the flow **checks 1Password for an existing `speedtest.cove.local` item first** and reuses it if present; only if absent does it generate new credentials, write them to 1Password (via a seed file + `cove creds 1p-bulk-write`), cache in Vault (via `cove creds vault-put`), and inject into the compose `.env`. Subsequent runs read the cached value. No manual key-setting, no weak default, no fail-loud-on-unset friction.
- **Version-pinned image** (no `latest`), non-root, memory-limited.
- **SQLite, single container** — no external DB to operate, no additional CVE surface beyond the app container.

## Compliance

- `## Test command`: `uv run --directory cli pytest -x -q -m "not e2e and not staging"` (tier 0).
- `## Test command (integration)`: `uv run --directory cli pytest -x -q -m "e2e and not staging"` (tier 1).
- Coverage matrix: update `docs/test-coverage-matrix.yaml`.

## Acceptance criteria

1. All Tier 0 tests pass (T0-1..T0-27), written red first.
2. `cove speedtest up` starts the tracker; `speedtest.cove` serves the UI through nginx.
3. `cove speedtest down/status/logs` work; down uses `stop`, status checks through nginx on 8443.
4. Landing page shows the `speedtest.cove` card; `cove status` reports it as optional.
5. PURPOSE.md, README, and `docs/speedtest.md` reflect the service.
6. Coverage matrix updated with new paths.
7. No `0.0.0.0` host port; nginx is the sole ingress; `APP_KEY` + admin credentials auto-generated and stored in 1Password + Vault, keyed by the `speedtest.cove.local` URL (shared across machines, reused if present).
8. Cleanup: worktree removed, PR merged (operator approval).

## Deferred (not in this PR)

- Notifications (webhook/apprise → ntfy) for bandwidth/latency thresholds — the dashboard is the MVP.
- Layering platform auth (bearer/basic) on `speedtest.cove` beyond the app's own login, if desired.
- Public status page for the WAN link (currently operator-facing only).
