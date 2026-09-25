---
type: implementation
timestamp: 2026-09-25T115800
unit: isolated staging E2E (parallel cove-staging compose project)
---

## Isolated staging E2E — the branch no longer deploys into the live stack

**Operator decision:** build the isolated staging E2E on different ports rather
than a Lima VM. Staging is now a parallel Docker Compose project
(`-p cove-staging`) in the same Colima VM, fully port/name/data-isolated from
the live stack.

### Why

`scripts/staging/{deploy,e2e,teardown}.sh` deployed the branch INTO the live
stack: `cove up` re-rendered nginx on 8443 and restarted live containers. That
is why staging E2E was skipped — it disturbed the live stack and the running
bb. Every conflict turned out to be solvable with env-driven seams the compose
file already had.

### How isolation is enforced

New `compose/docker-compose.staging.yml` (override file, used with
`-p cove-staging -f docker-compose.yml -f docker-compose.staging.yml`):

- **Container names.** `-p` does NOT prefix explicit `container_name` values
  (verified empirically on Docker Compose 5.5.1 — the rendered config kept the
  base's explicit names). The override therefore sets every
  `container_name` explicitly: `cove-staging-{forgejo,nginx,dnsmasq,dnsproxy,
  vault,litellm-db,litellm,headroom,forgejo-runner,speedtest-tracker,
  ade-server,tunnel}`. The file also sets `name: cove-staging` so omitting
  `-p` is still safe.
- **Ports.** nginx publishes only `127.0.0.1:9443→443`. Base nginx has a
  hard-coded `0.0.0.0:80:80` that cannot be env-remapped, so the override
  replaces the whole list with the `!override` YAML tag (verified working on
  compose 5.5.1; `ports: !override []` removes bindings entirely). Also
  dropped: forgejo SSH 2222, dnsmasq 5353/udp, litellm 4000, headroom 4001,
  speedtest 8982. Evidence: rendered config shows nginx with exactly one
  mapping and no other published host ports (full-stack render included).
- **Data.** `--env-file staging.env` points `COVE_DATA_ROOT`/
  `FORGEJO_DATA_ROOT`/`NGINX_CONF_DIR` at `~/Documents/cove-data-staging` and
  a staging-rendered nginx conf (Jinja2 render of the branch's
  `default.conf.j2` with `ade_port`). The live root is only ever READ (mkcert
  pair copied out, with a self-signed fallback; dnsmasq conf copied). No
  `cove` CLI call, so no 1Password/biometric path. ADE image tag isolated too
  (`cove-ade-staging:0.43.4`).
- **Drift guard.** The override redefines the nginx volume list; a unit test
  asserts its mount targets equal the base render's, so a future base mount
  addition cannot be silently dropped in staging.

### Files

- `compose/docker-compose.staging.yml` (new) — the override.
- `scripts/staging/deploy-isolated.sh` (new) — wheel build + venv, staging
  data tree prep, `compose -p cove-staging --profile ade up -d --build`,
  health wait (fail loud, 600s, diagnostics on timeout), prints
  `https://127.0.0.1:9443`.
- `scripts/staging/e2e.sh` — default URL `https://127.0.0.1:9443`, exports
  `BB_STAGING_URL`; scoped to the ADE staging module on 9443, full staging
  sweep only when pointed at the legacy 8443.
- `scripts/staging/teardown.sh` — isolated teardown (`compose down -v`,
  staging data-dir removal) plus new guards: project name must be
  staging-suffixed, data root must contain "staging" and never equal the live
  root, and the production-name list now includes every live container
  (incl. `cove-ade-server`). The legacy stop-list is now empty: live
  optional-profile containers (`cove-litellm`, `cove-headroom`) are production
  names and are never stopped by a staging teardown (that guard caught my
  first draft, which still listed them — red-green by the guard itself).
- `cli/tests/test_staging_isolation.py` (new, tier 0) — 11 tests parsing
  `docker compose config --format json`: project name (with and without
  `-p`), container-name isolation (ade set + full stack + prefix), nginx
  9443 remap, host-port collision checks (ade set + full stack), live
  data-root mount prohibition, staging-root usage, nginx volume target
  parity.
- `cli/tests/test_e2e_ade_staging.py` (new, tier 2 `staging` marker) —
  `BB_STAGING_URL` (default `https://127.0.0.1:9443`), `Host: ade.cove`:
  `/health` returns `"ok": true`; wrong Host does not reach bb; `/ws`
  upgrades to `101 Switching Protocols` through nginx (raw socket + TLS, no
  new deps — spike 2 confirmed standard upgrade headers suffice).
- Docs: `docs/services/ade.md` (isolated staging section), `AGENTS.md`
  (staging paragraph), `docs/test-coverage-matrix.yaml` (rows below).

### Coverage matrix honesty

- `GET /health on ade.cove`: happy now executable (was manual).
- `WebSocket upgrade (/ws) through ade.cove nginx (live)`: happy now
  executable — the 101 upgrade is genuinely asserted in the staging E2E.
- `ade container image build`: happy now executable — the isolated deploy
  builds with `--build` and the E2E proves the built image serves.
- Added two rows: isolated staging E2E (happy/sad executable, edge manual —
  no automated edge case) and cove-staging compose isolation
  (happy/sad/edge executable).

### Verification

- Red first: `tests/test_staging_isolation.py` run before the override
  existed → 1 failed + 10 errors; after the override (and one more red on
  full-stack port collisions from litellm/headroom/speedtest) → 11 passed.
- Isolated E2E run: deploy → healthy; `e2e.sh` → **3 passed**
  (health ok, wrong-Host isolation, WS 101).
- Full gate: `uv run --directory cli pytest -x -q -m "not e2e and not staging"`
  → **606 passed, 28 deselected** (was 595).
- Live-stack safety: `docker ps` before/after the deploy, E2E, and teardown —
  every live container unchanged (`Up 2 days` / 45-47h uptimes identical);
  only additions were the six `cove-staging-*` containers, removed by
  teardown along with the network, volumes, and staging data dir. (Note:
  `hal-dashboard` was crash-looping before this unit started — pre-existing,
  unrelated.)
- Teardown verified: no `cove-staging` containers/networks remain, staging
  data dir removed.

### Observations (not fixed here)

- The dual-marked `test_e2e_dns.py` staging tests target the LIVE stack on
  8443; live currently 404s `/config/ca` (stale live nginx conf predating
  that route). Pre-existing, unrelated to this unit; the isolated staging
  stack actually serves the route correctly. The live conf refresh is an
  operator `cove up`, deliberately not run by this unit.
- `scripts/staging/setup.sh` still gates on the LIVE 8443 ingress; it belongs
  to the legacy path and was left as-is.
