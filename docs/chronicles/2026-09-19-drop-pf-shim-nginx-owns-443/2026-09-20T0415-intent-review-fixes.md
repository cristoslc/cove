**Responding to:** code-review entry 2026-09-20T0410 (verdict needs_changes) — operator-approved fix dispatch

Intent: address review findings on PR #50. High: staging harness + e2e-marked
tests move 8443 -> 443 (setup.sh, deploy.sh, e2e.sh, test_e2e_dns.py,
test_litellm.py, test_speedtest.py). Medium: drop dead NGINX_HTTPS_PORT env
render in bringup.yml (after grep for consumers), fix AGENTS.md staging URL.
Low: status.py f-string ports, compose 443 why-comment, architecture.md table.
RGR: adjust failing expectations first where behavior is test-asserted, then
impl. Gate: `uv run --directory cli pytest -x -q -m "not e2e and not staging"`
green + `bash -n` staging scripts. No live-stack, sudo, or PR-state changes.