# Plan: ADE Harness Phase 1 — bb-server in Cove with `ade.cove` Ingress

**Status:** Active
**Created:** 2026-09-25
**ADR:** `docs/adr/adr-018-ade-agentic-harness.md` (Accepted)
**Musing:** `docs/musings/2026-09-24-bb-harness-in-cove.md`
**Branch:** `bb/agentic-harness-setup-for-cove-thr_zqcxmdcp5b`

## Goal

Stand up the bb server as a Cove-hosted, profiled service reachable at `ade.cove`, **without moving the operator's running bb instance**. This is the non-destructive half of ADR-018. Cutover of the live server is Phase 2 and does not belong to this sashay.

## Non-negotiable boundary

Phase 1 MUST NOT repoint, restart, or interfere with the operator's live bb server or host daemon. The `ade` server runs as a second instance alongside. Any step that would enroll the host against the live server, or move `~/.bb`, is out of scope.

## Deliverables

1. **`ade` compose profile** — a `bb-server` service in `compose/docker-compose.yml` under `profiles: ["ade"]`:
   - built from a new Dockerfile (`compose/ade/Dockerfile`) that installs the pinned `bb-app` npm package (Node base image, install scripts allowed for `better-sqlite3`, `node-pty`, `@parcel/watcher`),
   - data dir on a mounted volume under `${cove_data_root}/ade/` (Data in Documents),
   - bound so the cove network reaches it (see Spike 1),
   - container name `cove-ade-server`.
2. **`ade.cove` nginx site** — new server block in `compose/nginx/default.conf.j2` proxying to `cove-ade-server:38886`, following the `litellm.cove` block shape (WebSocket upgrade headers required; Spike 2), plus the dnsmasq/resolver entries in `bringup.yml`.
3. **`cove ade` CLI** — `cli/cove/ade.py` with `up`, `down`, `status`, `logs`, mirroring `cli/cove/runner.py` / `litellm.py`.
4. **bringup wiring** — `cove_profiles` handling for `ade`, data-dir creation, env-var plumbing in `bringup.yml` (image, container name, port, pinned version).
5. **Tests** — `cli/tests/test_ade.py` (unit, follows `test_runner.py`), plus a failure-expecting test written first (see Test plan).
6. **Docs** — `docs/services/ade.md` service page; README/AGENTS.md mention where the other optional services are documented.

## Spikes (run first; block the design if they fail)

1. **Bind address in container.** The bb server "listens on loopback by default." Determine the setting/flag (e.g., `--host 0.0.0.0`, env, or settings) that lets nginx and cove-network machines reach `cove-ade-server:38886`. If bb refuses a non-loopback bind without Connect, stop and report; this reshapes ingress.
2. **WebSocket + auth behind nginx.** Verify the bb web client works through a reverse proxy (upgrade headers, long-lived connections), and determine what auth — if any — the direct-URL mode carries. If it carries none, `ade.cove` needs an auth decision before it is exposed beyond loopback.
3. **Image build.** Confirm exact npm package pin, entrypoint command, data-dir flag, and that a headless container start reaches a healthy server. Reference: bb issue #3168 (downstream distributions pin `bb-app` as an npm dep); bb PR #4135 (headless server via `npx bb-app` is supported).

## Test plan

- **Failure-expecting test first (mandatory):** assert `cove ade status` reports unhealthy/absent when the container is not running — written before any implementation.
- **Unit:** profile detection, env plumbed into compose, container-name/port defaults, data-dir path resolution (`test_ade.py`).
- **Integration (existing marker rules):** nginx template renders the `ade.cove` block with the expected `proxy_pass` and upgrade headers.
- **Staging E2E:** `scripts/staging/e2e.sh` deploys the branch and checks `ade.cove` returns a healthy response via `curl -H "Host: ade.cove" https://127.0.0.1:8443/` (or the staging pattern).
- **Coverage matrix:** add an ADE row to `docs/test-coverage-matrix.yaml`.
- **Gate:** `uv run --directory cli pytest -x -q -m "not e2e and not staging"`.

## Rollback

Profiled service, branch-only, stable `cove` never reinstalled from a branch wheel. Rollback = leave the `ade` profile off (default); no effect on `cove up` for anyone not choosing it.

## Out of scope (deferred, named so they do not creep in)

- Phase 2: cutting the operator's live bb server into the container; host re-enrollment.
- Provider auth mechanics; `cove ade up` execution-machine containers (Phase 3).
- Bundle membership and `cove up` bundle UX (ADR-019).
- Any `cove project` per-project harness mode.

## Done looks like

`uv run --directory cli cove ade up` starts a bb server in a container, `cove ade status` reports it healthy, `ade.cove` serves the bb web UI through nginx over TLS, the unit suite passes, and the operator's live bb is untouched. Draft PR open with the chronicle interleaved.
