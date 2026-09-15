# Plan: Forgejo Actions Runner in cove (issue #48)

Source issue: https://git.cove/cristos/cove/issues/48 — "Add Forgejo Actions runner to cove (CI currently inert)".

## Problem

Forgejo Actions workflows are inert: no runner is registered, so no workflow ever runs.
Blocks the homelab knowledge-sync workflow (push-time CI design defeated by local fallback).

## Design decisions

- **Optional service pattern** (mirrors litellm/speedtest): compose service gated by
  `profiles: ["runner"]`, lifecycle via `cove runner up|down|status|logs`, nginx not required
  (runner is outbound-only: polls forgejo; no ingress route needed).
- **Image**: `codeberg.org/forgejo/forgejo-runner` pinned to a tag (e.g. `11` major, verify
  current at implementation), version-pinned per cove hardening convention.
- **Network**: default compose network (forgejo is on it). Runner reaches
  `http://forgejo:3000` directly; no Host-header workaround needed.
- **Registration is IaC**: `provision_forgejo.yml` already mints an admin API token via
  `docker exec ... admin user generate-access-token --scopes write:admin`. Reuse that token
  (or mint a dedicated one) to `GET /api/v1/actions/runners/registration-token`
  (instance-wide, admin-scoped), then register the runner non-interactively:
  `docker exec cove-forgejo-runner forgejo-runner register --no-interactive ...` OR write
  `config.yml` + registration via `forgejo-runner create-runner-file`. Prefer the
  idempotent pattern: registration file persisted under `${COVE_DATA_ROOT}/forgejo-runner/`,
  task skipped when already registered (idempotency check like other provisioning tasks).
- **Labels**: `ubuntu-latest:docker://gitea/runner-images:ubuntu-latest` (or pinned equivalent),
  `ubuntu-22.04:docker://...`, `docker:docker://` — final pins verified at implementation;
  jobs run Docker-in-Docker via the runner's own docker socket mount (`/var/run/docker.sock`)
  — colima on macOS hosts provides this socket.
- **Vault-backed secrets (stretch goal from issue)**: `cove up` mints a scoped runner Vault
  token (new policy `cove-runner`, path-restricted to `secret/data/op-cache/**` read-only —
  first-of-its-kind scoped pattern; only `admins` all-sudo policy exists today) and writes it
  to the runner's env. Workflows then `VAULT_TOKEN`-fetch KV entries directly. If scoped-token
  minting proves risky, fallback: document `VAULT_TOKEN` env injection via compose env from
  an existing token — never the root token.

## Implementation steps

1. **compose/docker-compose.yml**: add `forgejo-runner` service, `profiles: ["runner"]`,
   image `${FORGEJO_RUNNER_IMAGE:-codeberg.org/forgejo/forgejo-runner:11}`, container
   `cove-forgejo-runner`, volume `${FORGEJO_RUNNER_DATA_ROOT}/...:/data`, docker socket mount
   for job containers, memory limit, `restart: unless-stopped`, env from `.env`
   (FORGEJO_RUNNER_* vars). Mount `${COVE_DATA_ROOT}/forgejo/pages/sites` read-write IF the
   runner must serve deploy-pages jobs (see nginx comment compose/nginx/default.conf.j2:69-71).
2. **bringup.yml**: add cert SAN? (no ingress — skip), add `FORGEJO_RUNNER_*` vars to `.env`
   render (first-boot-only block), add data-dir loop entry for runner data root.
3. **provision_forgejo.yml**: add tasks:
   a. ensure runner registration: query registration token (admin API), run
      `forgejo-runner register --no-interactive` via docker exec (or `create-runner-file`),
      skip-if-registered idempotency check.
   b. (stretch) mint scoped Vault token for runner, store to runner env path.
4. **cli/cove/runner.py**: click group `cove runner` with `up|down|status|logs`, mirroring
   `speedtest.py` (`--profile runner` before `up`, stop not down, `.env` upsert pattern).
   Register in `cli/cove/cli.py` (app registration like cli.py:247-249).
5. **cli/cove/status.py**: add runner to `OPTIONAL_SERVICES` (status.py:33-37).
6. **compose/seeds/**: not needed (runner has no admin identity in 1P; registration token is
   ephemeral + derived). Skip seed.
7. **docs/services/forgejo-runner.md**: Quick Start, What it does, Labels, Registration
   (IaC), Vault secrets (stretch), Commands, Architecture (mermaid), Troubleshooting.
   State auth posture (test-enforced pattern per speedtest doc).
8. **docs/test-coverage-matrix.yaml**: add rows: `cove runner up`, `cove runner down`,
   `GET /api/v1/actions/...` registration path, trivial workflow executes.
9. **Tests** (`cli/tests/test_runner.py` mirroring test_speedtest.py):
   - compose service definition (profile, image pin, memory limit, socket mount)
   - CLI registration + commands shape
   - bringup.yml greps (.env vars, data-dir loop)
   - provision_forgejo.yml greps (registration-token query, skip-if-registered)
   - resources sync byte-compare
10. **Sync + verify**: `python3 cli/scripts/sync_compose_resources.py`, test gate
    `uv run --directory cli pytest -x -q -m "not e2e and not staging"`.

## Acceptance (from issue)

- [ ] `cove runner up` brings up a runner that shows as online in Forgejo admin
- [ ] A trivial workflow (echo) executes on push
- [ ] (stretch) workflow step reads a secret from Vault via `VAULT_TOKEN`

## Out of scope

- Pages deploy integration (separate concern; nginx comment already anticipates it)
- Auto-scaling / multiple runners