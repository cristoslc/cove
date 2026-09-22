**Responding to:** implementation dispatch for issue #51 (NODE_EXTRA_CA_CERTS docs on ca.cove config page)

Per operator request: "use then sashay" on issue #51 — implementing the plan at `docs/plans/51-document-node-extra-ca-certs.md`.

**Intent:** add a "Node.js / Electron clients" subsection to the "Trust this machine" section of `compose/nginx/config.html.j2`, extend `TestConfigHtmlRendering` in `cli/tests/test_e2e_dns.py` with assertions for `NODE_EXTRA_CA_CERTS`, `rootCA.pem`, `add-trusted-cert`, `update-ca-certificates`, plus a no-Jinja2-artifacts check for this template.

- **What:** docs-only template change + rendering test; checked `docs/test-coverage-matrix.yaml` — it has no config-page rendering entries (only litellm/speedtest/runner rows), so I will add a row for the new Node trust path.
- **Why:** Node.js ignores the OS trust store; operators hit `unable to verify the first certificate` with no documented fix.
- **Success:** template renders cleanly with `FULL_TEMPLATE_VARS`, new assertions pass, full local suite green (`not e2e and not staging`).