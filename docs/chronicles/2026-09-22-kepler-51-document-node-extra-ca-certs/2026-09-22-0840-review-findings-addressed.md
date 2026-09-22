# 2026-09-22 — Review findings addressed for #51

**Responding to:** code review (2026-09-22-0825-code-review.md)

## Findings and resolutions

1. **blocking — `curl -o` chicken-and-egg.** `ca.cove` is a 301 to
   `git.cove/config/ca` and the client does not trust the CA yet, so plain
   `curl -o` fails on both counts. Fixed: command is now
   `curl -kL -o cove-root-ca.pem https://ca.cove/config/ca`, with a sentence
   explaining why `-kL` is needed (skip cert verification + follow redirect).
   Test updated to assert the full corrected command.

2. **minor — "Electron main" misleading.** Node reads `NODE_EXTRA_CA_CERTS`
   during bootstrap and Chromium's network stack does not honor it from main.
   Reworded: set the variable in "the environment each app is launched from
   (launchd plist / systemd unit)". `launchctl setenv` caveat wording kept —
   review confirmed it accurate.

3. **nit — host path context.** `~/Documents/cove-data/certs/rootCA.pem` now
   annotated as "path on the Cove machine".

4. **nit — matrix `sad: skip` understated.** The presence-assertion test does
   exercise the sad direction; `docs/test-coverage-matrix.yaml` row updated to
   `sad: executable`.

## Verification

`uv run --directory cli pytest -x -q -m "not e2e and not staging"` →
442 passed, 25 deselected (153.64s).