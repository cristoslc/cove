**Responding to:** implementation checkpoint

Tests first (red confirmed): 5 tests failed against old source — new
`test_nginx_binds_443_directly` + `test_bringup_has_no_pf_or_tailscale_serve`
in test_cli.py, and the three source-string assertions in test_litellm /
test_speedtest flipped to exact `https://127.0.0.1:443/` patterns (plain "443"
would have matched "8443", so the f-string URL is the assertion target).

Source changes green:
- compose/docker-compose.yml: nginx `0.0.0.0:443:443` (kept `80:80`)
- compose/bringup.yml: pf-rdr task (~312) and tailscale-serve task (~149)
  deleted; tailscale status/DNS/IP fact-gathering kept (feeds summary msg)
- compose/group_vars/all.yml: `nginx_https_port: 443` — brings .env and the
  three bringup probe URLs along automatically
- cli/cove/status.py: NGINX_HTTPS_PORT = 443; refusal hint rewritten
  ("Is nginx up? Run `cove up`", `lsof -i :443`) — pf hint removed
- cli/cove/litellm.py:237, cli/cove/speedtest.py:281: probes now :443
- docs: architecture.md (diagram, ownership list, proxy section, DNS,
  pipeline, ports table), README.md, docs/services/litellm-proxy.md,
  docs/services/speedtest.md — minimal pf/8443/tailscale-serve removals

Grep gate: compose/ has zero hits for 8443/pfctl/rdr/tailscale-serve.
Checkpoint: 5 red tests now pass; full pytest gate next.