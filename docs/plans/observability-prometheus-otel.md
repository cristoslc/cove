# Plan: Observability Backend for Cove (Prometheus + Grafana + OTel)

> **Source:** `docs/musings/observability-prometheus-otel.md` → Parley record `docs/musings/parleys/2026-08-06-observability-platform.md`
>
> **Decision (operator, 2026-08-06):** build the **standard stack now** — Prometheus + Grafana with OTLP ingestion — as a first-class Cove service. The custom "step short of OTel" idea was dropped as contrary to Cove's identity of providing industry-standard tooling.

## Scope

Add an **observability backend** to Cove: an OTel collector (OTLP ingestion), Prometheus (time-series store/query), and Grafana (dashboards). Consumed by apps running on Cove via a documented ingestion endpoint (`otel.cove`) and a `cove observability init` CLI helper.

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
    Given the observability profile is not running
    When nginx starts
    Then it still starts (deferred upstream DNS resolution)
```

### FC-4: `cove observability init` app integration
```
Feature: App integration helper
  Scenario: init wires an app's compose service to the collector
    Given a compose file with a service `web`
    When I run `cove observability init web`
    Then it adds OTEL_EXPORTER_OTLP_ENDPOINT and OTEL_SERVICE_NAME env to `web`
    And it is idempotent (re-running makes no further change)

  Scenario: init on a missing service fails loud
    When I run `cove observability init nosuch`
    Then it exits non-zero with a clear error
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
- **T0-4** `test_services_bind_localhost_only` — no `ports:` with `0.0.0.0`; collector/prometheus/grafana bind `127.0.0.1` (FC-3).
- **T0-5** `test_nginx_renders_otel_server_block` — rendered `default.conf.j2` contains an `otel.cove` server block proxying to the collector, using a `set $...` deferred-DNS variable (FC-3).
- **T0-6** `test_nginx_renders_grafana_server_block` — `grafana.cove` server block present (FC-3).
- **T0-7** `test_collector_config_valid` — `otel-collector.yaml` is valid YAML and declares an OTLP receiver + prometheus exporter (FC-2).
- **T0-8** `test_prometheus_scrape_config` — prometheus.yml scrapes otel-collector and forgejo/vault (FC-5).
- **T0-9** `test_cli_observability_subcommands` — CLI module exposes `up/down/status/logs/init` (FC-1, FC-4).
- **T0-10** `test_landing_page_has_grafana` — landing.html has a grafana.cove card (FC-6).
- **T0-11** `test_bringup_sans_include_otel_grafana` — bringup.yml cert SANs include `otel.cove` and `grafana.cove` (FC-3). *(Note: `*.cove` wildcard likely already covers these — assert explicitly and add explicit SANs if not.)*
- **T0-12 (init)** `test_init_injects_env` + `test_init_idempotent` + `test_init_missing_service_fails` — behavior of `cove observability init` via CliRunner against a temp compose file (FC-4).
- **T0-13 (inverse-assertion)** `test_otel_routes_reject_unknown_host` — a Host header for an arbitrary non-cove domain does NOT route to the collector (adversarial/inverse, FC-3).

### Tier 1 — integration E2E (live stack, `-m e2e and not staging`)
- **T1-1** `test_observability_up_starts_containers` — `cove observability up` starts all three (FC-1).
- **T1-2** `test_otel_health` — `otel.cove/health` returns 200 (FC-2).
- **T1-3** `test_grafana_ui` — `grafana.cove` serves Grafana (FC-3).
- **T1-4** `test_metric_roundtrip` — emit an OTLP metric, confirm it lands in Prometheus (FC-2). *(May be partially manual if no app fixture exists.)*

### Coverage matrix self-heal
Add `docs/test-coverage-matrix.yaml` paths for: `cove observability up/down/status/init`, `otel.cove` ingestion, `grafana.cove`, and the collector/prometheus/grafana compose definitions — with `blast_radius` and Happy/Sad/Edge/Corner cells per the litellm precedent.

## Implementation (post-red tests)

### 1. Compose — `compose/docker-compose.yml`
Add three services under `profiles: ["observability"]`, mirroring the litellm pattern:
- **otel-collector**: OTel Collector image, `read_only: true`, `tmpfs`, OTLP receiver on `4317`/`4318`, exports to Prometheus. Config at `compose/observability/otel-collector.yaml`.
- **prometheus**: Prometheus image, scrape config at `compose/observability/prometheus.yml`, scrapes otel-collector + forgejo + vault. Bind `127.0.0.1`.
- **grafana**: Grafana image, provisioned datasource pointing at prometheus, bind `127.0.0.1`. Data under `${COVE_DATA_ROOT}/observability/`.
- Optional: nginx-prometheus-exporter if we want nginx metrics (defer — not required by contracts).

### 2. Config files — `compose/observability/`
- `otel-collector.yaml` (OTLP receiver + prometheus exporter).
- `prometheus.yml` (scrape targets).
- `grafana/provisioning/` (datasource + default dashboard).

### 3. Nginx — `compose/nginx/default.conf.j2`
Add `otel.cove` and `grafana.cove` server blocks, mirroring the litellm block: `server_name otel.cove otel.cove.local;`, `set $otel_upstream http://otel-collector:4318;`, `set $grafana_upstream http://grafana:3000;` with deferred DNS via `resolver 127.0.0.11`. Regenerate `default.conf` (the file has both `.j2` and rendered `.conf` — both must be updated).

### 4. CLI — `cli/cove/observability.py`
Mirror `litellm.py`: `up/down/status/logs` calling `docker compose --project-directory ... up -d --profile observability`. Plus `init <service>`: parse target compose file, inject `OTEL_EXPORTER_OTLP_ENDPOINT` + `OTEL_SERVICE_NAME`, idempotent. Register in `cli/cove/cli.py`.

### 5. Landing page — `compose/nginx/landing.html`
Add grafana.cove (and optionally otel.cove) card; add to the `services` health array.

### 6. bringup.yml
Add `otel.cove`/`otel.cove.local`/`grafana.cove`/`grafana.cove.local` to cert SANs and hosts (mirror litellm). Verify against `*.cove` wildcard; add explicit entries for determinism.

### 7. Bundled resources
Mirror litellm: copy the new `compose/observability/` dir + updated files into `cli/cove/resources/compose/` so the packaged CLI ships them.

### 8. Docs
- Add `docs/observability.md` (the FC-6 contract): ingestion endpoint, auth, `cove observability init` usage, dashboards.
- PURPOSE.md/README already updated to list observability (done pre-plan); confirm consistency.
- Add AGENTS.md `cove observability` command note if warranted.

## Security posture
- All three containers bind `127.0.0.1` only; no `0.0.0.0` host ports. Isolation from the ingress, not route whitelist (matches litellm precedent).
- `otel-collector` read-only rootfs. Version-pinned images (no `latest`).
- Grafana admin password from `${GRAFANA_ADMIN_PASSWORD:-}` (env, default weak for localhost — flag as local-only).
- mTLS from the local CA for `otel.cove` ingestion per parley T3; if SDK/operator friction proves prohibitive, fall back to a Vault-issued bearer token (documented flip condition).

## Compliance
- `## Test command`: `uv run --directory cli pytest -x -q -m "not e2e and not staging"` (tier 0).
- `## Test command (integration)`: `uv run --directory cli pytest -x -q -m "e2e and not staging"` (tier 1).
- Coverage matrix: update `docs/test-coverage-matrix.yaml`.

## Acceptance criteria
1. All Tier 0 tests pass (T0-1..T0-13), written red first.
2. `cove observability up` starts all three; `otel.cove` ingests OTLP; `grafana.cove` serves UI.
3. `cove observability init <svc>` wires an app service idempotently.
4. PURPOSE.md, README, and `docs/observability.md` reflect the service.
5. Coverage matrix updated with new paths.
6. Cleanup: worktree removed, PR merged (operator approval via morning review).

## Deferred (not in this PR)
- nginx-prometheus-exporter / nginx access-log metrics.
- Grafana operator dashboard suite beyond a default datasource.
- Auto-instrumentation agent/template beyond the env-injection helper.
