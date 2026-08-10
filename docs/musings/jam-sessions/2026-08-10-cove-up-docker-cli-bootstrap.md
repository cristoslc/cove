# Jam: `cove up` docker CLI bootstrap

## 2026-08-10 10:10 — Problem

- `cove up` failed at the "Start Colima" step: `dependency check failed for docker: docker not found`.
- Colima was installed, but the docker CLI client (`brew install docker`) was missing on this machine.
- Decision: bootstrap the docker CLI inside the bringup playbook rather than install it manually.

## 2026-08-10 10:10 — Fix

- Added two tasks to `bringup.yml` before the "Ensure Colima is running" block:
  - "Detect docker CLI presence (macOS)": `command -v docker`, `failed_when: false`, registered as `docker_cli_detect`.
  - "Bootstrap docker CLI via Homebrew (macOS)": runs `brew install docker` only when `docker_cli_detect.rc != 0`.
- Result: pending verification.
- Next: run `cove up` and confirm it passes the Colima/bootstrap step.

## Notes

- `~/.config/cove` is NOT a git repo — no checkpoints there; the change is a direct edit to `bringup.yml`.
- Colima runs the docker runtime; only the client binary was missing.

## 2026-08-10 11:07 — Second failure: missing docker compose plugin

- After bootstrapping the docker CLI, `cove up` failed at "Bring up pod via docker compose":
  `unknown flag: --project-directory`. Root cause: the docker CLI alone has NO `compose`
  subcommand — `docker compose` is a separate plugin (`brew install docker-compose`).
- `brew info docker-compose` caveat: the plugin must be discoverable via
  `cliPluginsExtraDirs` in `~/.docker/config.json` pointing at `/opt/homebrew/lib/docker/cli-plugins`.
- Fix (in `compose/bringup.yml` at repo root — canonical source):
  - "Detect docker compose plugin (macOS)": `docker compose version`, `failed_when: false`.
  - "Bootstrap docker compose plugin via Homebrew (macOS)": `brew install docker-compose`
    only when the detect step failed.
  - "Register Homebrew docker cli-plugins dir for compose (macOS)": merges
    `cliPluginsExtraDirs` into `~/.docker/config.json` via a python3 JSON merge (preserves
    existing auths/credsStore/plugins — did NOT overwrite, which would have clobbered ghcr auth).
- Added regression test `test_bringup_bootstraps_compose_plugin` in `cli/tests/test_cli.py`
  (fails before fix, passes after). Tested the JSON merge standalone against a copy of the real
  config: ghcr.io auth, credsStore, currentContext, and plugins all preserved.
- Next: run full non-e2e suite; then rebuild+reinstall the `cove` uv tool so the bootstrapped
  docker-compose plugin change actually ships (AGENTS.md now documents the promote/rollback flow).
