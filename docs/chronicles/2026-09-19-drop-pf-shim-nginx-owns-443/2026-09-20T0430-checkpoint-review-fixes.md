**Responding to:** code-review entry 2026-09-20T0410 (needs_changes) — all findings fixed, gate green

RGR loop: 3 new guard tests in `test_cli.py::TestDeploymentManifests` written
RED first (dead env export, staging scripts 8443, e2e test files 8443), then
GREEN.

HIGH — staging harness + e2e tests → 443:
- scripts/staging/setup.sh (probes), deploy.sh (printed URL), e2e.sh (comment
  + STAGING_URL default): 8443 → 443
- test_e2e_dns.py COVE_HTTPS_PORT default "8443" → "443";
  test_litellm.py TestE2ELitellmStack (8 URLs + docstring);
  test_speedtest.py TestE2ESpeedtestStack (2 URLs); conftest.py +
  test_e2e_stateless.py docstring mentions 8443 → 443

MEDIUM:
- bringup.yml env render: dropped `NGINX_HTTPS_PORT={{ nginx_https_port }}`
  (source + bundled). Grep confirmed no consumer: compose no longer reads it;
  nginx_https_port group_var kept (feeds probe/provision URLs in bringup,
  provision_pages, group_vars).
- AGENTS.md staging section → https://127.0.0.1:443

LOW:
- status.py: refusal detail + `lsof` hint now f-string the NGINX_HTTPS_PORT
  constant (no hardcoded 443 literals left)
- compose/docker-compose.yml (+ bundled): why-comment above 0.0.0.0:443:443
- docs/architecture.md network table: nginx entry → `0.0.0.0:443`,
  `0.0.0.0:8080` (matches compose publish; was `127.0.0.1:443`, `:8080`)

Gate: `uv run --directory cli pytest -x -q -m "not e2e and not staging"` →
**445 passed** (was 442; +3 guard tests). `bash -n` on all four staging
scripts: OK. No live-stack/sudo/PR-state changes. Ready for the closure
loop's staging e2e step.