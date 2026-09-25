---
type: checkpoint
timestamp: 2026-09-25T011503
responding-to: plan implementation steps 2 and 3 — compose profile, nginx site, bringup wiring, CLI, tests, docs
---

## ADE Phase 1 implemented; unit gate green

**Responding to:** the plan's Deliverables 1–6, after all three spikes passed.

**What landed**

- `compose/ade/Dockerfile` — `node:24-bookworm-slim`, `npm install -g --allow-scripts=better-sqlite3,node-pty,@parcel/watcher bb-app@${BB_APP_VERSION}`, entrypoint `bb-app --data-dir /data --server-bind-host 0.0.0.0 --server-port 38886`. Pin default `0.43.4`.
- `compose/docker-compose.yml` — `ade` service under `profiles: ["ade"]`, container `cove-ade-server`, data volume `${COVE_DATA_ROOT}/ade:/data`, wildcard bind env, healthcheck on `/health`, no host ports, 2G memory cap, build arg `ADE_BB_APP_VERSION`.
- `compose/nginx/default.conf.j2` — `map $http_upgrade $connection_upgrade` at http level plus the `ade.cove` / `ade.cove.local` block: variable upstream `http://cove-ade-server:38886` + `resolver 127.0.0.11`, `proxy_http_version 1.1`, `Upgrade`/`Connection` headers, buffering off, 3600s timeouts. Edited only the `.j2`; `default.conf` is generated.
- `compose/bringup.yml` — cert SANs, cert-validation list and `/etc/hosts` entries for `ade.cove`/`ade.cove.local`; `${cove_data_root}/ade` data dir; `.env` plumbing for `ADE_IMAGE`, `ADE_CONTAINER_NAME`, `ADE_BB_APP_VERSION`, `ADE_PORT`.
- `cli/cove/ade.py` — `up`/`down`/`status`/`logs` mirroring `runner.py`/`litellm.py`. `status` explicitly reports `NOT RUNNING` and exits 1 when the container is absent before probing health. Registered in `cli.py`; added to `status.OPTIONAL_SERVICES` so `cove up` reconciles a running `ade` profile and `cove status` lists it.
- `cli/tests/test_ade.py` — 31 tests: compose definition, CLI wiring, nginx render (upstream + upgrade headers), bringup wiring, optional-service registration, resources sync. Includes the mandatory failure-expecting `TestStatusFailureMode` written and run before `ade.py` existed (failed with `ModuleNotFoundError: cove.ade`, the right reason).
- `docs/services/ade.md`, README row + link, AGENTS.md bullet, ADE rows in `docs/test-coverage-matrix.yaml`.

**Verification:** `uv run --directory cli pytest -x -q -m "not e2e and not staging"` → **582 passed, 25 deselected**. `docker compose --profile ade config` parses and resolves the service (container, image, profile, volume, build args confirmed). The Dockerfile image was built and run headless in Spike 3; nginx proxying was proven end-to-end in Spike 2/3.

**Deliberate non-actions:** stable `cove` tool never reinstalled from this branch; no staging deploy attempted (would touch the live stack); the operator's live bb on 38886 stays untouched. Phase 2 (host enrollment, live cutover) is untouched.

**Commits in this unit:** <this commit>.
