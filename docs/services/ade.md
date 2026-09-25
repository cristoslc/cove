# ADE — Agentic Development Environment (bb server)

Optional Cove service. Runs the pinned [`bb-app`](https://www.npmjs.com/package/bb-app)
server — the bb agentic harness — in a container on the cove network and serves
the bb web UI at `https://ade.cove/` through nginx.

See ADR-018 (`docs/adr/adr-018-ade-agentic-harness.md`) and the Phase 1 plan
(`docs/plans/ade-harness-phase1.md`).

## Quick Start

```bash
cove ade up        # build + start the ADE server (profile: ade)
cove ade status    # container + /health through nginx
cove ade logs -f   # tail server output
cove ade down      # stop (data preserved)
```

Then open `https://ade.cove/`. The service is **off by default**; nothing is
started unless the `ade` profile is chosen (`cove ade up` or `cove up` with the
profile active).

## What It Does

The ADE runs `bb-app` — a single server that stores threads, the database, and
settings, and dispatches work to enrolled execution machines. Phase 1 stands up
the server only; it does not touch the operator's existing bb instance.

- **Container:** `cove-ade-server` (service name `ade`), built from
  `compose/ade/Dockerfile` on `node:24-bookworm-slim`, pinned to
  `bb-app@0.43.4` via the `ADE_BB_APP_VERSION` build arg.
- **Data:** `/data` inside the container is `${cove_data_root}/ade/` on the
  host (Data in Documents), so the SQLite database and thread state survive
  image upgrades.
- **Bind:** `BB_SERVER_BIND_HOST=0.0.0.0` inside the container so nginx and
  other cove-network machines reach it (compose env, port `BB_SERVER_PORT`).
  The port has one source of truth: `ADE_PORT`, threaded into the compose env,
  the container healthcheck, and the nginx upstream. No host port is published.
- **Ingress:** `ade.cove` / `ade.cove.local` server block in
  `compose/nginx/default.conf.j2`, proxied to the stable compose service alias
  `ade` on `ADE_PORT` with WebSocket upgrade headers (`/ws` upgrades to
  `101 Switching Protocols` through nginx).

## Auth posture

bb's direct-URL mode is **unauthenticated by design**. The upstream project
documents wildcard binding as "security-sensitive, for compatibility only":
the public API permits command execution and file reads, and it has no
application login. This service therefore relies on the Cove network and
ingress as its trust boundary — the same boundary that already fronts Forgejo,
Vault, and the rest of the harbor. Do not expose `ade.cove`, or the container
port, beyond that boundary (no Funnel, no public internet, no untrusted LAN).

### Access control (enforced at nginx)

Because the upstream carries no auth, the `ade.cove` location enforces the
network posture rather than assuming it:

```
allow 127.0.0.1;
allow ::1;
allow 10.0.0.0/8;
allow 172.16.0.0/12;
allow 192.168.0.0/16;
allow 100.64.0.0/10;
deny all;
```

Operator decision 2026-09-25 widened the list: private-range clients reach
`ade.cove` directly — LAN (`10/8`, `192.168/16`), direct tailnet IPs
(`100.64.0.0/10`), container ranges (`172.16.0.0/12`), and loopback. Only
public-internet sources are denied. Host browser access, Tailscale Serve, and
cove-network machines all continue to work.

Ingress auth (e.g. basic auth or an SSO-ish layer at nginx) is a planned
addition; until then `deny all` for non-private sources is the only control.
Do not remove it without replacing it.

`bb Connect` remains an optional operator choice for push notifications and
universal links; it is not required for `ade.cove` and is not configured here.

## Configuration

The ADE port has one live-path source of truth: the Ansible var **`ade_port`**
(`compose/group_vars/all.yml`). `cove up` renders the nginx upstream from it and
re-syncs the composed `.env` line `ADE_PORT` from it on every run, so the
container's `BB_SERVER_PORT`, its healthcheck, and nginx's proxy target cannot
drift.

| Variable | Default | Purpose |
|---|---|---|
| `ade_port` (Ansible: group_vars / host_vars) | `38886` | **Live-path knob.** Change this and re-run `cove up`; it drives the nginx upstream and the `.env` `ADE_PORT`. |
| `ade_container_name` (Ansible) | `cove-ade-server` | Container name; re-synced into `.env` `ADE_CONTAINER_NAME` on `cove up`. |
| `ADE_BB_APP_VERSION` | `0.43.4` | Pinned `bb-app` npm version (Dockerfile build arg). |
| `ADE_IMAGE` | `cove-ade:0.43.4` | Built image tag; bringup derives the tag from `ADE_BB_APP_VERSION`. |
| `ADE_MEM_LIMIT` | `2G` | Container memory limit. |
| `ADE_PORT` (compose `.env`) | `38886` | Container `BB_SERVER_PORT` and healthcheck; **derived from `ade_port` and rewritten on every `cove up`** — do not edit it by hand as a durable override. |

**To change the port:** set `ade_port` in `host_vars/<hostname>.yml` (or
`group_vars/all.yml`) and re-run `cove up`. Editing `ADE_PORT` directly in the
compose `.env` is not a supported override: nginx is rendered by bringup from
the Ansible var, so a hand-edited `.env` would move the container while nginx
kept proxying to the old port — and the next `cove up` rewrites it anyway.

## Isolated staging E2E

The staging E2E for ADE runs against an **isolated** Docker Compose project
(`cove-staging`) in the same Colima VM — not against the live stack. The
legacy in-live mode (running `cove up` from the branch, testing on port 8443)
disturbed the live containers, so it is no longer the default.

```bash
scripts/staging/deploy-isolated.sh <branch>   # build wheel, bring up cove-staging
scripts/staging/e2e.sh                        # tier 2 tests against https://127.0.0.1:9443
scripts/staging/teardown.sh <branch>          # compose down -v + remove staging data
```

Isolation contract (asserted by `cli/tests/test_staging_isolation.py`, which
parses `docker compose -p cove-staging ... config`):

- **Project/name:** `-p cove-staging`; every `container_name` is explicitly
  `cove-staging-*` in `compose/docker-compose.staging.yml` (compose does NOT
  prefix explicit `container_name` values with the project name, so the
  override is required — otherwise staging would reuse the live names).
- **Ports:** nginx publishes only `127.0.0.1:9443→443`; the forgejo SSH,
  dnsmasq UDP, litellm, headroom, and speedtest host bindings are removed
  (`ports: !override []` — the `!override` tag replaces the base list). ADE
  has no host port in either mode; it is reached through nginx by `Host:`.
- **Data:** `COVE_DATA_ROOT`/`FORGEJO_DATA_ROOT` point at
  `~/Documents/cove-data-staging` (override with `COVE_STAGING_DATA_ROOT`);
  the live root is only ever read to copy the mkcert pair (falls back to a
  self-signed cert) and the dnsmasq conf. No 1Password/biometric path is
  involved and the `cove` CLI is never invoked.
- **Tests:** `cli/tests/test_e2e_ade_staging.py` (`@pytest.mark.staging`),
  base URL from `BB_STAGING_URL` (default `https://127.0.0.1:9443`):
  `/health` with `Host: ade.cove` returns `"ok": true`, a wrong `Host`
  (e.g. `git.cove`) does not reach bb, and `/ws` upgrades to
  `101 Switching Protocols` through nginx (raw-socket TLS, no extra deps).

The `ade.cove` access-control list (above) still applies to staging traffic:
host-originated requests arrive at nginx as the Docker gateway IP
(`172.16.0.0/12`) and are allowed.

## Spike results (Phase 1)

- **Bind:** `--server-bind-host 0.0.0.0` / `BB_SERVER_BIND_HOST` binds wildcard
  IPv4 with no bb Connect pairing; `0.0.0.0` is one of only two accepted values.
- **WebSocket + auth:** the web client uses a browser WebSocket at `/ws`; nginx
  needs `proxy_http_version 1.1` plus `Upgrade`/`Connection` from a `map`, and
  no buffering. Direct-URL mode carries no auth (above).
- **Image:** `npx bb-app` / `npm install -g bb-app@<pin>` starts a headless
  server; `--data-dir` (or `BB_DATA_DIR`) points at the volume; `/health`
  returns `{"ok":true}`.

## Out of scope (Phase 2)

Cutting the operator's live bb server into this container, host re-enrollment,
provider CLI logins in volumes, execution-machine containers (`cove ade up` as
a machine provider), and bundle membership. This page documents server
stand-up only.

## What It Does NOT Do

- **No host port.** The container is reached only over the cove network through
  nginx; there is no `127.0.0.1` mapping.
- **No application auth.** See "Auth posture".
- **No enrollment.** Phase 1 starts the server; it does not enroll the host or
  any other machine.
- **No 1Password seed.** The server has no shared admin identity; identities are
  managed by bb itself.
