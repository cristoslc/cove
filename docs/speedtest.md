# Speedtest Tracker for Cove

Speedtest Tracker monitors the operator's **internet connection** — uptime, latency, download/upload bandwidth, jitter, and packet loss — via scheduled Ookla `speedtest` CLI runs. It is an **optional, profiled** Cove service (`profile: speedtest`), mirroring the `litellm` pattern. It does **not** monitor Cove's own services (that stays with OpenObserve via the blackbox prober).

## Quick Start

```shell
# No manual APP_KEY setup needed — `cove speedtest up` auto-generates it
# and stores it in 1Password + Vault + the compose .env on first run.
cove speedtest up

# Check it's running
cove speedtest status
```

The tracker is accessible at `https://speedtest.cove.local/` through Cove's nginx ingress (port 8443 → 443 via pf). The container itself binds to `127.0.0.1:8982` only — no published `0.0.0.0` host port.

## Admin identity (unified Cove admin)

The Speedtest Tracker admin login uses the **unified Cove admin identity** (see [ADR-017](adr/adr-017-unified-cove-admin-identity.md)):

- **Email:** `admin@cove.local` — the shared Cove admin email, identical on every machine.
- **Password:** a word-based passphrase (hyphen-separated words), generated once and shared across machines.
- **Storage:** stored in the shared 1Password item `Speedtest Tracker`, keyed to `https://speedtest.cove.local/`, reused across machines.

Because the item is shared and URL-keyed, the same admin identity works on all the operator's machines — the first machine seeds it, the rest inherit it.

## APP_KEY + admin credentials (shared, URL-keyed — no manual setup)

`SPEEDTEST_APP_KEY` is the encryption key Speedtest Tracker uses for stored data. The admin username, admin password, and APP_KEY are stored together in a **single shared 1Password item titled `Speedtest Tracker`, keyed to the `https://speedtest.cove.local/` URL** — **not** per-hostname. Because the item is shared, the **same credentials work on all the operator's machines**; there is no manual key-setting and no fail-loud-on-unset friction.

On every `cove speedtest up`:
1. The flow **checks 1Password for an existing `speedtest.cove.local` item first** (via `cove creds vault-get` on the shared op_ref `op://Private/Speedtest Tracker/app_key`) and **reuses it if present** — no regeneration.
2. Only if no such shared item exists does it generate a random admin username, admin password, and APP_KEY, write them to 1Password via the `compose/seeds/speedtest-creds.yaml` seed (`cove creds 1p-bulk-write <seed> --execute`, rendering to the shared `Speedtest Tracker` item in the `Private` vault), cache in Vault via `cove creds vault-put`, and inject `SPEEDTEST_APP_KEY=<key>` into the compose `.env` (idempotent — no duplicate lines).

On subsequent runs, the shared item / cached value is reused — no regeneration, no duplicate 1Password item. If you set `SPEEDTEST_APP_KEY` yourself in the environment or `.env`, that value is honored directly. Because the op_ref is URL-keyed (not hostname-keyed), the same item is reused across machines — the first machine seeds it, the rest inherit it.

## Auth Posture (security)

`speedtest.cove` is LAN/Tailscale-reachable (nginx publishes `0.0.0.0:8443`), so auth is required, not cosmetic.

The pinned image (`lscr.io/linuxserver/speedtest-tracker:v1.14.5-ls162`, upstream Speedtest Tracker v1.14.5) **enforces app login on first run**. The UI redirects unauthenticated visitors to a login screen; the default credentials are `admin@example.com` / `password` and **must be changed on first login** via the Users page. The admin identity is the unified Cove admin (`admin@cove.local` + word-based passphrase, see [ADR-017](adr/adr-017-unified-cove-admin-identity.md)). This is a real login gate — it is NOT an unauthenticated-by-default dashboard.

**Posture:** app-login enforced (Speedtest Tracker's own authentication). No nginx basic-auth fallback is required because the pinned version enforces login. `APP_KEY` and the admin credentials are stored in a single shared 1Password item keyed to `https://speedtest.cove.local/` (reused across machines) and cached in Vault (see above) and used to encrypt stored data.

> **Guard:** if a future version bump ships an unauthenticated-by-default dashboard, this posture is violated and the deploy must layer nginx basic-auth on the `speedtest.cove` block (or pin back to an auth-enforcing version) before exposing it. See the T0-26 auth-posture contract.

## What's Hardened

| Layer | Mitigation |
|-------|-----------|
| **Network** | Binds to `127.0.0.1:8982` only. No `0.0.0.0` host port; reachable only through nginx. |
| **Auth** | App login enforced on the pinned version; default `admin@example.com`/`password` must be changed. Admin identity is the unified Cove admin (`admin@cove.local` + word-based passphrase, see [ADR-017](adr/adr-017-unified-cove-admin-identity.md)); `APP_KEY` auto-generated, stored in one shared 1Password item (URL-keyed to `https://speedtest.cove.local/`, reused across machines) + Vault. |
| **Version** | Pinned to `v1.14.5-ls162` (no `latest`). |
| **Database** | SQLite single container — no external DB to operate, no extra CVE surface. |
| **Non-root** | Runs as the configured `PUID`/`PGID` user (default 1000:1000), not root. |
| **Memory** | Memory-limited (512M default). |
| **Health check** | Docker health check on the web root. |
| **Data** | Persisted under `${COVE_DATA_ROOT}/speedtest/` (volume-mounted `/config`). |

## Optional schedule

Set `SPEEDTEST_SCHEDULE` (cron format) to run tests automatically, e.g. `0 */6 * * *`. Optionally pin `SPEEDTEST_SERVERS` (comma-separated Ookla server IDs) and prune old results with `PRUNE_RESULTS_OLDER_THAN` (days). These pass through to the container env.

## Configuration

Data lives at `~/Documents/cove-data/speedtest/`. The `.env` is written by `cove up` from `bringup.yml`; `SPEEDTEST_APP_KEY` is auto-generated and injected by `cove speedtest up` (first run), not a static default. Subsequent `cove up` runs won't overwrite your changes.

## What it does NOT do

- Does not monitor Cove's own service availability (that stays with OpenObserve).
- No public status page (operator-facing only).
- No notifications wiring yet (deferred).

## Lifecycle

- `cove speedtest up` — start (uses `--profile speedtest`, does not touch core services).
- `cove speedtest down` — stop (uses `stop`, preserves data).
- `cove speedtest status` — check through nginx on `speedtest.cove` via 8443.
- `cove speedtest logs` — tail logs.
