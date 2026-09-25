---
type: review-response
timestamp: 2026-09-25T012919
responding-to: code review of PR #55 returning ACTIONABLE (8 findings)
---

## Review response — all 8 findings fixed

**Responding to:** the PR #55 code review, which returned ACTIONABLE with three MUST FIX and five ALSO FIX findings. Each was fixed red-green: a failing test written first, then the fix, then the gate.

### MUST FIX

**1. Inert `ADE_PORT` — now threaded end to end.** `ADE_PORT` is the single source of truth:
- `compose/docker-compose.yml:286` `BB_SERVER_PORT: "${ADE_PORT:-38886}"` and `:288` healthcheck `http://127.0.0.1:${ADE_PORT:-38886}/health`.
- `compose/nginx/default.conf.j2:203` `set $ade_upstream http://ade:{{ ade_port | default('38886') }};`.
- `compose/ade/Dockerfile:20` CMD dropped `--server-port`/`--server-bind-host` (explicit flags were overriding env, which is exactly the drift bug); the port now comes from `BB_SERVER_PORT` (`Dockerfile:7` default, compose override).
- Tests: `test_ade_port_is_threaded_from_ade_port`, `test_ade_healthcheck_port_is_threaded`, `test_ade_dockerfile_does_not_hardcode_port`, `test_ade_upstream_port_is_threaded`.

**2. Unauthenticated exec surface — ingress now enforces the posture.** `compose/nginx/default.conf.j2:210-213` added access control inside the `ade.cove` location:
```
allow 127.0.0.1; allow ::1; allow 172.16.0.0/12; deny all;
```
Evidence I gathered before choosing this: `cove_default` is `172.18.0.0/16` and **all host-originated traffic (fj/curl/browser) logs as `172.18.0.1`**, the Docker gateway. So the operator's host-browser and Tailscale-Serve paths (both terminate on the host) remain allowed, while LAN (`192.168/10`) and direct-tailnet (`100.64/10`) clients are denied. This narrows exposure without locking out the operator's own path. Tests: `test_ade_location_restricts_access`. The explicit acceptance that direct-LAN/direct-tailnet `ade.cove` access is now blocked, and that widening is an operator decision, is recorded in `docs/services/ade.md` ("Access control") and `docs/adr/adr-018-ade-agentic-harness.md` ("Phase 1 implementation note"). **Raised to the operator in the reply.**

**3. Coverage matrix no longer overclaims.** `docs/test-coverage-matrix.yaml`: the live `/health` and `/ws` rows and the image-build row are downgraded to `manual`; added an executable "ade.cove access control" row. `cove ade up` sad/edge now have real tests (`TestUpFailureModes`), and I added symmetric `TestDownFailureModes` so the down cells are honest too.

### ALSO FIX

**4. Stable service alias.** nginx now targets `http://ade:<port>` (the compose service alias), not the overridable `container_name`; a test asserts `cove-ade-server` never appears in the rendered config (`test_ade_upstream_uses_stable_service_alias`).

**5. Cert-SAN test de-tautologized.** `test_cert_sans_exact_ade_pair` asserts the exact pair `"ade.cove" "ade.cove.local"` in the cert-validation loop.

**6. `TimeoutExpired` handled.** `cli/cove/ade.py:93` catches it and falls through to `UNREACHABLE`; the same latent bug in `cli/cove/litellm.py:243` is fixed identically. Tests: `test_status_reports_unreachable_on_timeout` (ade) and `TestStatusRobustness` (litellm).

**7. Docker stderr echoed.** `cli/cove/ade.py:79-80` echoes the compose `ps` stderr on failure; mirrored in `cli/cove/litellm.py:232-233`. Test: `test_status_echoes_docker_stderr_on_ps_failure`.

**8. Image tag cannot drift.** `compose/bringup.yml:506` derives `ADE_IMAGE` from `ade_bb_app_version`: `cove-ade:{{ ade_bb_app_version | default('0.43.4') }}`. Test: `test_ade_image_tag_derives_from_pinned_version`.

### Verification

- Focused: `pytest tests/test_ade.py tests/test_litellm.py::TestStatusRobustness` → 42→45 passed (green after red).
- Gate: `uv run --directory cli pytest -x -q -m "not e2e and not staging"` → **595 passed, 25 deselected** (was 582).
- `docker compose --profile ade config` resolves `BB_SERVER_PORT=38886` and the threaded healthcheck.
- Live stack untouched: only read-only `docker network inspect` / `docker logs` were used; operator's bb on 38886 still 200.

### Not fixed

None. All eight findings are addressed.

**Commits in this unit:** <this commit>.
