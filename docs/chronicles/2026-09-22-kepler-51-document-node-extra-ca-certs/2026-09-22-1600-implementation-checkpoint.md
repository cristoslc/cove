**Responding to:** implementation complete for #51 (NODE_EXTRA_CA_CERTS docs)

Per operator request: "use then sashay" on issue #51 — implementation done and committed.

**Status update (checkpoint):**

- `compose/nginx/config.html.j2` — added "Node.js / Electron clients" `<h3>` under "Trust this machine": the `export NODE_EXTRA_CA_CERTS=~/Documents/cove-data/certs/rootCA.pem` fix, download-first `curl -o cove-root-ca.pem https://ca.cove/config/ca` path, durable OS-store alternatives (macOS `security add-trusted-cert`, Linux `update-ca-certificates`), and the `launchctl setenv` non-durability caveat.
- `cli/tests/test_e2e_dns.py` — `TestConfigHtmlRendering` grew `test_config_html_documents_node_ca_trust` (asserts `NODE_EXTRA_CA_CERTS`, `rootCA.pem`, `add-trusted-cert`, `update-ca-certificates`) and `test_config_html_no_jinja2_artifacts` (no `{{`/`{%` in render).
- `docs/test-coverage-matrix.yaml` — added row "config page documents Node/Electron CA trust (NODE_EXTRA_CA_CERTS)" (happy/edge executable; the matrix had no prior config-page row).

**Test results:** `uv run --directory cli pytest -x -q -m "not e2e and not staging"` → **442 passed, 25 deselected** (91.76s). Manual render with `FULL_TEMPLATE_VARS` equivalent vars: clean, all four fragments present, no unresolved Jinja.

Committed as efbb1c3, pushed to `fjl`.