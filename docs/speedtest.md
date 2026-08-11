# Speedtest Tracker for Cove

Speedtest Tracker monitors the operator's **internet connection** — uptime, latency, download/upload bandwidth, jitter, and packet loss — via scheduled Ookla `speedtest` CLI runs. It is an **optional, profiled** Cove service (`profile: speedtest`), mirroring the `litellm` pattern. It does **not** monitor Cove's own services (that stays with OpenObserve via the blackbox prober).

## Quick Start

```shell
# Set the required app key (no default — `cove speedtest up` fails loud if unset)
export SPEEDTEST_APP_KEY="base64:$(openssl rand -base64 32)"

# Start the tracker
cove speedtest up

# Check it's running
cove speedtest status
```

The tracker is accessible at `https://speedtest.cove.local/` through Cove's nginx ingress (port 8443 → 443 via pf). The container itself binds to `127.0.0.1:8982` only — no published `0.0.0.0` host port.

## Auth Posture (security)

`speedtest.cove` is LAN/Tailscale-reachable (nginx publishes `0.0.0.0:8443`), so auth is required, not cosmetic.

The pinned image (`lscr.io/linuxserver/speedtest-tracker:v1.14.5-ls162`, upstream Speedtest Tracker v1.14.5) **enforces app login on first run**. The UI redirects unauthenticated visitors to a login screen; the default credentials are `admin@example.com` / `password` and **must be changed on first login** via the Users page. This is a real login gate — it is NOT an unauthenticated-by-default dashboard.

**Posture:** app-login enforced (Speedtest Tracker's own authentication). No nginx basic-auth fallback is required because the pinned version enforces login. `APP_KEY` is required (no weak default) and used to encrypt stored data.

> **Guard:** if a future version bump ships an unauthenticated-by-default dashboard, this posture is violated and the deploy must layer nginx basic-auth on the `speedtest.cove` block (or pin back to an auth-enforcing version) before exposing it. See the T0-26 auth-posture contract.

## What's Hardened

| Layer | Mitigation |
|-------|-----------|
| **Network** | Binds to `127.0.0.1:8982` only. No `0.0.0.0` host port; reachable only through nginx. |
| **Auth** | App login enforced on the pinned version; default `admin@example.com`/`password` must be changed. `APP_KEY` required, no weak default. |
| **Version** | Pinned to `v1.14.5-ls162` (no `latest`). |
| **Database** | SQLite single container — no external DB to operate, no extra CVE surface. |
| **Non-root** | Runs as the configured `PUID`/`PGID` user (default 1000:1000), not root. |
| **Memory** | Memory-limited (512M default). |
| **Health check** | Docker health check on the web root. |
| **Data** | Persisted under `${COVE_DATA_ROOT}/speedtest/` (volume-mounted `/config`). |

## Optional schedule

Set `SPEEDTEST_SCHEDULE` (cron format) to run tests automatically, e.g. `0 */6 * * *`. Optionally pin `SPEEDTEST_SERVERS` (comma-separated Ookla server IDs) and prune old results with `PRUNE_RESULTS_OLDER_THAN` (days). These pass through to the container env.

## Configuration

Data lives at `~/Documents/cove-data/speedtest/`. The `.env` is written by `cove up` from `bringup.yml`; `SPEEDTEST_APP_KEY` is sourced from the operator's host vars / 1Password ref, not a literal. Subsequent `cove up` runs won't overwrite your changes.

## What it does NOT do

- Does not monitor Cove's own service availability (that stays with OpenObserve).
- No public status page (operator-facing only).
- No notifications wiring yet (deferred).

## Lifecycle

- `cove speedtest up` — start (uses `--profile speedtest`, does not touch core services).
- `cove speedtest down` — stop (uses `stop`, preserves data).
- `cove speedtest status` — check through nginx on `speedtest.cove` via 8443.
- `cove speedtest logs` — tail logs.
