**Responding to:** task completion — plan implemented, test gate green

Status update for PR #50. Plan `docs/plans/drop-pf-shim-nginx-owns-443.md`
implemented via TDD (5 tests red first, then source changes, then green).

Files changed:
- compose/docker-compose.yml — nginx publish `0.0.0.0:443:443` (kept `80:80`)
- compose/bringup.yml — deleted "Forward localhost:443 → localhost:8443 via pf"
  task and "Configure tailscale serve for HTTPS on port 443" task; kept the
  tailscale status/DNS/IP fact-gathering tasks (feed the summary message)
- compose/group_vars/all.yml — `nginx_https_port: 443` (flows into .env and
  the three bringup probe URLs automatically)
- cli/cove/status.py — `NGINX_HTTPS_PORT = 443`; refusal detail + hints
  rewritten for 443, pf hint replaced with "Is nginx up? Run `cove up`"
- cli/cove/litellm.py — health probe `https://127.0.0.1:443/health/readiness`
- cli/cove/speedtest.py — health probe `https://127.0.0.1:443/`
- docs/architecture.md, README.md, docs/services/litellm-proxy.md,
  docs/services/speedtest.md — pf NAT / tailscale serve / 8443 statements
  updated to nginx-binds-443-directly

Tests added/updated (tests-first, all red before source change):
- cli/tests/test_cli.py: `test_nginx_binds_443_directly` (asserts compose
  contains `"0.0.0.0:443:443"` and no `NGINX_HTTPS_PORT:-8443` fallback),
  `test_bringup_has_no_pf_or_tailscale_serve` (asserts no `rdr-anchor`,
  `pfctl`, or `tailscale serve` in bringup.yml)
- cli/tests/test_litellm.py `test_no_direct_port_access_in_cli` — exact
  `https://127.0.0.1:443/` pattern instead of bare "8443"
- cli/tests/test_speedtest.py same flip in
  `test_speedtest_status_checks_through_nginx` and
  `test_no_direct_port_access_in_cli`

Test gate: `uv run --directory cli pytest -x -q -m "not e2e and not staging"`
→ **442 passed, 25 deselected in ~64s. All green.**

Grep gate: compose/ has zero hits for `8443`, `pfctl`, `rdr`,
`tailscale serve`. Untouched by design: scripts/staging/* URLs,
e2e/staging-marked test URLs, historical docs/plans/musings — those track
the live-stack staging URL and are outside this branch's source-of-truth
surface; they'll need a pass when staging next runs against the live stack.

Unexpected findings:
- AGENTS.md line 82 references staging at `https://127.0.0.1:8443` — left
  as-is (describes the staging harness, not the product ingress).
- Remaining 8443 references live in docs/plans (historical), docs/musings,
  docs/chronicles, and one line in docs/architecture/data-inventory.md
  (GCM credential naming + pf NAT row) — historical records, not edited.
- jinja2 import-resolution LSP errors in the three test files are
  pre-existing (venv resolution), unrelated to this change.

Not done here (per plan/operator): live cutover (`tailscale serve reset`,
`cove down && cove up`, sudo) and promote (post-merge reinstall) remain
operator-assisted steps.