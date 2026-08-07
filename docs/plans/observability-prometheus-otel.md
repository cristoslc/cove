# Plan: Observability Backend for Cove (OpenObserve)

> **Source:** `docs/musings/observability-prometheus-otel.md` → Parley record `docs/musings/parleys/2026-08-06-observability-platform.md`
>
> **Decision (operator, 2026-08-06):** observability is a first-class Cove service.
>
> **REVISED (2026-08-07, parley T7):** the backend is a **single OpenObserve all-in-one container**, NOT the Prometheus+Grafana assembled stack described in the body below. The body is retained as the historical superseded spec. **The operative spec is the T7 revision.** See `docs/musings/parleys/2026-08-06-observability-platform.md#T7`.

## T7 REVISION — Operative spec (supersedes body)

**Backend:** one **OpenObserve** container (`openobserve.cove`), OTel-native, ingesting OTLP at `otel.cove` for metrics + logs + traces + prebuilt APM dashboards in a single UI. Single binary, no external DB, object-storage (S3/MinIO) backend — aligns with Cove's existing MinIO.

**App-facing contract (unchanged, durable):**
- OTel instrumentation (the transferable, industry-standard practice — the durable asset).
- OTLP ingestion at `otel.cove` through the nginx ingress, **bearer-token auth** at the boundary.
- `cove observability init` CLI helper (idempotent compose/.env edit injecting `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SERVICE_NAME`, token header).

**Dropped:** Prometheus store, Grafana dashboards, custom dashboard-building. The dev sees OpenObserve's prebuilt APM dashboards; no query-language skill required.

**Boundaries:**
- Distributed tracing ships natively (OTLP spans) — no separate service.
- Profiling stays per-app (pprof/JFR/py-spy) — not a platform service.

**Implementation changes vs body:**
- `compose/docker-compose.yml`: replace otel-collector/prometheus/grafana with **one `openobserve` service** (always-on, no published host ports, `restart: unless-stopped`, version-pinned image, data under `${COVE_DATA_ROOT}/observability/`).
- `compose/observability/`: replace collector/prometheus/grafana configs with OpenObserve config/env (admin creds required — no weak default; object storage backend config).
- `compose/nginx/default.conf.j2` (+ rendered `.conf`): `otel.cove` → OpenObserve OTLP endpoint with bearer-token auth; `openobserve.cove` → OpenObserve UI.
- `cli/cove/observability.py`: `up/down/status/logs/init` against the `openobserve` service; `init` injects OTLP env + token.
- `cli/cove/resources/compose/`: bundle updated configs (drift test guards).
- Docs (PURPOSE.md/README/`docs/observability.md`): reference OpenObserve, not Grafana. README Services table → OpenObserve row (`openobserve.cove`).
- Coverage matrix: update observability paths (OpenObserve compose, OTLP ingestion auth, `openobserve.cove` UI).
- Tests: rewrite `cli/tests/test_observability.py` T0/T1 for the OpenObserve service (single container, OTLP auth at nginx, `init` behavior, resources-drift, inverse-assertion for unauthenticated OTLP).

---

## ORIGINAL SPEC (superseded by T7 — retained for history)

> **Decision (operator, 2026-08-06):** build the **standard stack now** — Prometheus + Grafana with OTLP ingestion — as a first-class Cove service. The custom "step short of OTel" idea was dropped as contrary to Cove's identity of providing industry-standard tooling. *(Superseded by T7: single OpenObserve instead.)*

## Scope

Add an **observability backend** to Cove: an OTel collector (OTLP ingestion), Prometheus (time-series store/query), and Grafana (dashboards). Consumed by apps running on Cove via a documented ingestion endpoint (`otel.cove`) and a `cove observability init` CLI helper.

**First-class = always-on (no profile).** The operator's decision ("standard stack now, alongside forge/vault") means the three services run on every `cove up` with `restart: unless-stopped`, matching forgejo/vault — NOT the optional litellm-profile pattern. `cove observability down` stops them; `up` restarts; but they are present by default.

**Adversarial-review fixes folded in (2026-08-06):** no weak default Grafana password; Vault bearer-token auth primary (mTLS dropped); no published host ports; resources-tree drift test; profile-vs-first-class resolved to always-on.

**Out of scope (boundaries from the parley):**
- **Profiling** (pprof/JFR/py-spy) is a per-app concern, NOT a platform service.
- **Distributed tracing** is enabled via OTLP spans when a real cross-service need arises — the collector+OTLP wire protocol already carries spans; no separate service is built now.

## Behavioral Contracts (BDD — drive test design)

These are the Gherkin-style contracts the implementation MUST satisfy. Each maps to tests (see Test Plan). Written pre-implementation (red).

### FC-1: `cove observability up` brings up the stack
```
Feature: Observability lifecycle
  Scenario: up starts the profiled stack
    Given the cove CLI is installed
    When I run `cove observability up`
    Then the otel-collector, prometheus, and grafana containers start
    And the command exits 0
    And grafana.cove resolves to the Grafana UI

  Scenario: down stops the stack (data preserved)
    When I run `cove observability down`
    Then the three containers stop
    And the data directory is preserved

  Scenario: status reports health
    When I run `cove observability status`
    Then it reports the running state of each container
```

### FC-2: OTLP ingestion endpoint
```
Feature: OTLP ingestion
  Scenario: apps emit metrics via OTLP
    Given an app on Cove configured with OTEL_EXPORTER_OTLP_ENDPOINT
    When the app emits a metric over OTLP
    Then the collector accepts it
    And Prometheus stores it
    And the metric is queryable via PromQL on grafana.cove/prometheus

  Scenario: collector is read-only at the filesystem
    Then the otel-collector container has read_only: true
```

### FC-3: Nginx routing + isolation
```
Feature: Ingress isolation
  Scenario: otel.cove routes to the collector
    Given nginx is the sole ingress
    When a request arrives for Host: otel.cove
    Then it proxies to the otel-collector
    And the collector binds to 127.0.0.1 only (no host port)

  Scenario: grafana.cove routes to Grafana
    When a request arrives for Host: grafana.cove
    Then it proxies to grafana
    And grafana binds to 127.0.0.1 only

  Scenario: missing service does not break nginx
    Given the observability containers are down
    When nginx starts
    Then it still starts (services are always-on but nginx must not hard-depend on their readiness)
```

### FC-4: `cove observability init` app integration
```
Feature: App integration helper
  Scenario: init wires an app's compose service to the collector
    Given a compose file with a service `web`
    When I run `cove observability init web`
    Then it adds OTEL_EXPORTER_OTLP_ENDPOINT, OTEL_SERVICE_NAME, and OTEL_EXPORTER_OTLP_HEADERS (Vault bearer token) env to `web`
    And it is idempotent (re-running makes no further change)

  Scenario: init on a missing service fails loud
    When I run `cove observability init nosuch`
    Then it exits non-zero with a clear error

  Scenario: init requires an auth token source
    Given no Vault bearer token is available
    When I run `cove observability init web`
    Then it fails loud with guidance to provision a token (no silent unauthenticated wiring)
```

### FC-4b: Ingestion auth
```
Feature: Ingestion auth
  Scenario: otel.cove requires a bearer token
    Given an OTLP request without an auth header
    When it reaches otel.cove
    Then it is rejected (401/403) at the nginx boundary

  Scenario: otel.cove accepts a valid bearer token
    Given an OTLP request with a valid Vault-issued bearer token
    When it reaches otel.cove
    Then it is forwarded to the collector and accepted
```

### FC-5: Self-observation
```
Feature: Cove observes itself
  Scenario: forgejo/vault metrics are scraped
    Given forgejo and vault expose Prometheus /metrics
    When the prometheus scrape config targets them
    Then their metrics appear in Prometheus
```

### FC-6: Docs reflect the new service
```
Feature: Documentation
  Scenario: service is documented
    Then PURPOSE.md lists observability
    And README Services table lists the observability row
    And a docs/observability.md guide exists
```

## Test Plan (pre-implementation, red-green-refactor)

New test file: `cli/tests/test_observability.py` (mirrors `test_litellm.py` structure).

### Tier 0 — unit/config (always run, `-m "not e2e and not staging"`)
Written FIRST (red), before any implementation:
- **T0-1** `test_compose_services_exist` — compose defines `otel-collector`, `prometheus`, `grafana` (FC-1/FC-2).
- **T0-2** `test_observability_profile` — the three services have `profiles: ["observability"]` (FC-1).
- **T0-3** `test_collector_read_only` — otel-collector has `read_only: true` (FC-2).
- **T0-4** `test_services_publish_no_host_ports` — collector/prometheus/grafana declare **no `ports:`** at all (match forgejo/vault, not litellm). nginx and Prometheus reach them via compose service names over the internal network (FC-3).
- **T0-5** `test_nginx_renders_otel_server_block` — rendered `default.conf.j2` contains an `otel.cove` server block proxying to the collector, using a `set $...` deferred-DNS variable (FC-3).
- **T0-6** `test_nginx_renders_grafana_server_block` — `grafana.cove` server block present (FC-3).
- **T0-7** `test_collector_config_valid` — `otel-collector.yaml` is valid YAML and declares an OTLP receiver + prometheus exporter (FC-2).
- **T0-8** `test_prometheus_scrape_config` — prometheus.yml scrapes otel-collector and forgejo/vault (FC-5).
- **T0-9** `test_cli_observability_subcommands` — CLI module exposes `up/down/status/logs/init` (FC-1, FC-4).
- **T0-10** `test_landing_page_has_grafana` — landing.html has a grafana.cove card (FC-6).
- **T0-11** `test_bringup_sans_include_otel_grafana` — bringup.yml cert SANs include `otel.cove` and `grafana.cove` (FC-3). *(Note: `*.cove` wildcard likely already covers these — assert explicitly and add explicit SANs if not.)*
- **T0-12 (init)** `test_init_injects_env` + `test_init_injects_token_header` + `test_init_idempotent` + `test_init_missing_service_fails` + `test_init_no_token_fails_loud` — behavior of `cove observability init` via CliRunner against a temp compose file (FC-4, FC-4b).
- **T0-13 (inverse-assertion)** `test_otel_routes_reject_unknown_host` — a Host header for an arbitrary non-cove domain does NOT route to the collector (adversarial/inverse, FC-3).
- **T0-14 (auth)** `test_otel_requires_bearer_token` — nginx `otel.cove` server block enforces a token; unauthenticated request rejected (FC-4b).
- **T0-15 (secrets)** `test_grafana_password_default_empty` — `GRAFANA_ADMIN_PASSWORD` defaults to empty and `up` fails loud if unset (never a weak literal) (FC-6/security).
- **T0-16 (resources drift)** `test_resources_tree_in_sync` — SHA-256 of `compose/observability/` (and updated nginx/bringup) equals `cli/cove/resources/compose/observability/` (and matching files), so the packaged CLI can't ship stale config (security/integrity).

### Tier 1 — integration E2E (live stack, `-m e2e and not staging`)
- **T1-1** `test_observability_up_starts_containers` — `cove observability up` starts all three (FC-1).
- **T1-2** `test_otel_health_auth` — `otel.cove/health` returns 401/403 without a token, 200 with a valid one (FC-4b).
- **T1-3** `test_grafana_ui` — `grafana.cove` serves Grafana (FC-3).
- **T1-4** `test_metric_roundtrip` — emit an OTLP metric with the token, confirm it lands in Prometheus (FC-2). *(May be partially manual if no app fixture exists.)*

### Coverage matrix self-heal
Add `docs/test-coverage-matrix.yaml` paths for: `cove observability up/down/status/init`, `otel.cove` ingestion, `grafana.cove`, and the collector/prometheus/grafana compose definitions — with `blast_radius` and Happy/Sad/Edge/Corner cells per the litellm precedent.

## Implementation (post-red tests)

### 1. Compose — `compose/docker-compose.yml`
Add three services (always-on, NO profile, NO published host ports, matching forgejo/vault). Mirror litellm's hardening (read_only, tmpfs, version-pinned images):
- **otel-collector**: OTel Collector image, `read_only: true`, `tmpfs`, OTLP receiver on `4317`/`4318`, exports to Prometheus. Config at `compose/observability/otel-collector.yaml`. Requires an auth token check at nginx (FC-4b). Reachable by nginx/Prometheus via compose service name — no `ports:`.
- **prometheus**: Prometheus image, scrape config at `compose/observability/prometheus.yml`, scrapes otel-collector + forgejo + vault. No `ports:` — served through nginx `grafana.cove/prometheus` or internal network.
- **grafana**: Grafana image, provisioned datasource pointing at prometheus, `GRAFANA_ADMIN_PASSWORD` required (no weak default), admin/user provisioning. No `ports:` — served via `grafana.cove`. Data under `${COVE_DATA_ROOT}/observability/`.

Grafana/prometheus/collector all reachable only via nginx. If a `grafana.cove/prometheus` path is impractical, expose a dedicated `prometheus.cove` server block instead — but never a host port.

### 2. Config files — `compose/observability/`
- `otel-collector.yaml` (OTLP receiver + prometheus exporter).
- `prometheus.yml` (scrape targets).
- `grafana/provisioning/` (datasource + default dashboard).

### 3. Nginx — `compose/nginx/default.conf.j2`
Add `otel.cove` and `grafana.cove` server blocks. For `otel.cove`, enforce a **bearer token at the nginx boundary** (FC-4b): check the `Authorization` header against the expected token before `proxy_pass` to the collector — the sole-ingress boundary is where the token is validated, preserving ADR-014. Use `set $otel_upstream http://otel-collector:4318;` / `set $grafana_upstream http://grafana:3000;` so nginx starts even if the containers are briefly down (always-on but not hard-start-blocked). Regenerate `default.conf` (both `.j2` and rendered `.conf` must be updated).

### 4. CLI — `cli/cove/observability.py`
Mirror `litellm.py`: `up/down/status/logs`. Plus `init <service>`: parse the target compose file, inject `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SERVICE_NAME`, and `OTEL_EXPORTER_OTLP_HEADERS` (Authorization: Bearer <token>); idempotent; **fail loud if no token source is available** (no silent unauthenticated wiring). The token comes from Vault (provisioned during `cove observability up`, stored/read via the existing secrets path). Register in `cli/cove/cli.py`.

### 5. Landing page — `compose/nginx/landing.html`
Add grafana.cove (and optionally otel.cove) card; add to the `services` health array.

### 6. bringup.yml
Add `otel.cove`/`otel.cove.local`/`grafana.cove`/`grafana.cove.local` to cert SANs and hosts (mirror litellm). Also provision the Vault bearer token for ingestion during bringup/provision, and store it via the existing secrets path so `cove observability up` and `init` can read it.

### 7. Bundled resources
Mirror litellm: copy the new `compose/observability/` dir + updated files into `cli/cove/resources/compose/` so the packaged CLI ships them.

### 8. Docs
- Add `docs/observability.md` (the FC-6 contract): ingestion endpoint, auth, `cove observability init` usage, dashboards.
- PURPOSE.md/README already updated to list observability (done pre-plan); confirm consistency.
- Add AGENTS.md `cove observability` command note if warranted.

## Security posture
- **No published host ports** for collector/prometheus/grafana (match forgejo/vault). Reachable only through nginx. nginx is the sole ingress (ADR-014), and it publishes `0.0.0.0:8443`, so these are LAN/Tailscale-reachable — auth is required, not cosmetic.
- **Ingestion auth is required at the nginx boundary (FC-4b):** `otel.cove` validates a bearer token (Authorization header) before proxying to the collector. Unauthenticated OTLP is rejected 401/403. This is enforced at the ingress, not just the collector, preserving the sole-ingress invariant and preventing LAN telemetry injection/Prometheus fill.
- **Auth token:** Vault-issued bearer token is the **primary** mechanism (injected via `OTEL_EXPORTER_OTLP_HEADERS`). **mTLS from the local CA is dropped** — OTel SDKs don't natively do client certs, so it was unimplementable as the primary path; it can be documented as a manual hardening option later.
- **Grafana admin password:** defaults to **empty**, and `up` fails loud if unset (mirrors litellm's `UI_PASSWORD: ${...:-}`). NO weak literal default — `grafana.cove` is network-reachable.
- **Read-only hardening:** otel-collector `read_only: true`. Version-pinned images (no `latest`).
- **Resources-tree drift guarded:** T0-16 hashes `compose/observability/` and updated nginx/bringup against `cli/cove/resources/compose/` so the packaged CLI can't ship stale config.

## Compliance
- `## Test command`: `uv run --directory cli pytest -x -q -m "not e2e and not staging"` (tier 0).
- `## Test command (integration)`: `uv run --directory cli pytest -x -q -m "e2e and not staging"` (tier 1).
- Coverage matrix: update `docs/test-coverage-matrix.yaml`.

## Acceptance criteria
1. All Tier 0 tests pass (T0-1..T0-16), written red first.
2. `cove observability up` starts all three; `otel.cove` ingests OTLP **only with a valid bearer token**; `grafana.cove` serves UI.
3. `cove observability init <svc>` wires an app service idempotently, including the token header.
4. PURPOSE.md, README, and `docs/observability.md` reflect the service.
5. Coverage matrix updated with new paths.
6. No published host ports for the three services; nginx is the sole ingress.
7. Cleanup: worktree removed, PR merged (operator approval via morning review).

## Deferred (not in this PR)
- nginx-prometheus-exporter / nginx access-log metrics.
- Grafana operator dashboard suite beyond a default datasource.
- Auto-instrumentation agent/template beyond the env-injection helper.
