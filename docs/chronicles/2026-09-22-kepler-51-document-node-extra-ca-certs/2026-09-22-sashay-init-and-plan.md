**Responding to:** sashay start (step 3, chronicle init) — issue #51.

Sashay initialized on branch `kepler/51-document-node-extra-ca-certs`.
Worktree: `/Users/cristos/kepler/worktrees/cove-51-document-node-extra-ca-certs-fc75d72f`.

Pre-branch artifacts committed and pushed:
- Musing: `docs/musings/2026-09-22-node-extra-ca-certs.md` (384a804) — Node.js never reads the OS trust store; captured the Kepler/GitKraken reproduction and the launchctl caveat.
- Plan: `docs/plans/51-document-node-extra-ca-certs.md` (72d44db) — docs-only change to `compose/nginx/config.html.j2` (Node/Electron trust section) plus rendering tests in `cli/tests/test_e2e_dns.py`. Key finding: `/config/ca` already serves the CA with a stable filename and `~/Documents/cove-data/certs/rootCA.pem` is the stable host path, so no new endpoint or compose changes are needed.

Intent post: implementation subagent will be dispatched next with the chronicle-first prompt. Definition of done for the implementation: template renders cleanly, new `TestConfigHtmlRendering` assertions pass, full local test suite green.