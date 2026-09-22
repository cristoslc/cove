# Plan: Document NODE_EXTRA_CA_CERTS on ca.cove config page

**Branch:** `kepler/51-document-node-extra-ca-certs`
**Issue:** [#51 — Node/Electron clients do not trust Cove CA — document NODE_EXTRA_CA_CERTS on ca.cove config page](https://gitlab.cove.local:3003/cristos/cove/-/issues/51)
**Musing:** `docs/musings/2026-09-22-node-extra-ca-certs.md`

## Problem

Cove's root CA is installed into the OS trust store only. Node.js and
Electron use their bundled Mozilla CA list and never read the OS store,
so any Node-based client making HTTPS calls to `*.cove` / `*.cove.local`
fails TLS with `unable to verify the first certificate`. Nothing in Cove
currently documents this or points at a fix (`grep -r NODE_EXTRA_CA_CERTS`
is zero hits).

## Scope

Documentation-only change to the ca.cove config page template, plus a
rendering test. No nginx, compose, bringup, or CLI structural changes:
`/config/ca` already serves `rootCA.pem` with a stable download filename
(`cove-config-locations.conf`), and the host-side CA lives at
`~/Documents/cove-data/certs/rootCA.pem` (`compose/group_vars/all.yml`).

## Changes

### 1. `compose/nginx/config.html.j2`

Add a "Node.js / Electron clients" subsection under "Trust this machine":

- The fix: `export NODE_EXTRA_CA_CERTS=~/Documents/cove-data/certs/rootCA.pem`
  (then restart the Node process).
- For machines without the local file: download first —
  `curl -o cove-root-ca.pem https://ca.cove/config/ca` — then point the
  env var at the downloaded path.
- Durable OS-store alternative (makes Node trust moot):
  - macOS: `sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain cove-root-ca.pem`
  - Linux: `sudo cp cove-root-ca.pem /usr/local/share/ca-certificates/cove-root-ca.crt && sudo update-ca-certificates`
- Caveat note: `launchctl setenv NODE_EXTRA_CA_CERTS` does not survive
  reboot and is per-machine; durable per-app env belongs in each app's
  packaging (launchd plist / systemd unit / Electron main).

### 2. `cli/tests/test_e2e_dns.py` — `TestConfigHtmlRendering`

Extend the existing rendering tests:

- New test asserting the rendered page contains `NODE_EXTRA_CA_CERTS`,
  `rootCA.pem`, and the durable-alternative command fragments
  (`add-trusted-cert`, `update-ca-certificates`).
- Keep the no-Jinja2-artifact style of neighboring tests.

## Verification

- `uv run --directory cli pytest -x -q -m "not e2e and not staging"`
- Template renders cleanly with `FULL_TEMPLATE_VARS` (no unresolved Jinja).

## Out of scope

- Serving new endpoints or changing `/config/ca`.
- Per-app env packaging helpers (each app owns its env).
- docs/ prose beyond the config page (issue asks only for the page).

## Test coverage matrix

Update `docs/test-coverage-matrix.yaml` entry for the config page
rendering tests to cover the Node section (happy: env var documented;
edge: no unresolved template vars).