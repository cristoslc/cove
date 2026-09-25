---
type: checkpoint
timestamp: 2026-09-25T010910
responding-to: plan spike 3 — image pin/entrypoint/headless health, plus end-to-end nginx websocket confirmation
---

## Spike 3 — headless image pin works; `/ws` upgrades 101 through nginx

**Responding to:** the plan's Spike 3 (image build) and the remaining half of Spike 2 (real websocket upgrade through a reverse proxy).

**Pin/entrypoint/data-dir confirmed.** `bb-app@0.43.4` is the current `latest`; it declares `engines: node ^22.19 || ^24 || ^26` and exposes bins `bb-app`, `bb`, `bb-server`, `bb-host-daemon`. The launcher accepts `--data-dir <path>`, `--server-bind-host`, `--server-port`, `--host-daemon-port` (config keys `BB_DATA_DIR`, `BB_SERVER_BIND_HOST`, `BB_SERVER_PORT`, `BB_HOST_DAEMON_PORT`). Node 24's npm 11 accepts `--allow-scripts=better-sqlite3,node-pty,@parcel/watcher` (npm 12+ requires it). Image built from `node:24-bookworm-slim` + `npm install -g bb-app@0.43.4`; the first build ran the native add-on scripts and succeeded.

**Headless container health confirmed.** `docker run` the built image exposed on `127.0.0.1:39999:38886`; after ~25s the launcher reported server + co-located host daemon running, data dir `/data`, and `GET /health` returned `{"ok":true,...}` HTTP 200. Container stayed `Up`.

**Nginx end-to-end confirmed.** A throwaway `nginx:1.27-alpine` on a private network proxied to the container using the exact block shape the implementation will use (variable upstream + `resolver 127.0.0.11`, `proxy_http_version 1.1`, `Upgrade`/`Connection` from a `map`, `proxy_buffering off`). Results through the proxy:

- `GET /health` with `Host: ade.cove` → `200`.
- `GET /internal/ws` (host-daemon token endpoint) without a token → `401` from bb (proxied correctly; auth enforced by bb).
- `GET /ws` with websocket upgrade headers → **`HTTP/1.1 101 Switching Protocols`** with `Connection: upgrade` from nginx. This is the browser realtime channel and it upgrades with the planned config.

**Commits in this unit:** Dockerfile added under `compose/ade/` (committed with the implementation).

**Evidence artifacts (not committed):** build log, container log, proxy probe. Spike containers (`cove-ade-spike`, `ade-spike`, `ade-nginx-spike`, `ade-spike-net`) and the temp nginx conf were torn down after the probes; the operator's live bb server (port 38886) and host daemon were never touched — every probe used port 38899/39998/39999 and isolated data dirs.
