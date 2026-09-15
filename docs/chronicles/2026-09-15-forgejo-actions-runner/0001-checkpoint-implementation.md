**Responding to:** Implementation of issue #48 (Forgejo Actions runner)

Checkpoint: All 6 work units complete. Forgejo Actions runner added as optional Cove service.

**Files changed:**
- `compose/docker-compose.yml` — added `forgejo-runner` service (profile: runner, image pinned to `data.forgejo.org/forgejo/runner:11`, docker socket mount, memory limit 512M)
- `compose/bringup.yml` — `FORGEJO_RUNNER_*` env vars in .env render, data-dir entry
- `compose/provision_forgejo.yml` — IaC registration tasks (fetch registration token via admin API, `--no-interactive` register, skip-if-registered idempotency)
- `cli/cove/runner.py` — click group `runner` with `up|down|status|logs`
- `cli/cove/cli.py` — registered `runner` group
- `cli/cove/status.py` — runner in OPTIONAL_SERVICES
- `cli/tests/test_runner.py` — 32 tests (compose, CLI, bringup, provision, resources sync, auth posture)
- `docs/services/forgejo-runner.md` — Quick Start, Labels, Registration (IaC), Commands, Architecture (mermaid), Troubleshooting
- `docs/test-coverage-matrix.yaml` — runner rows added

**Test results:** 411 passed, 0 failed (e2e/staging excluded; pre-existing E2E stateless timeout unrelated)

**Acceptance checklist:**
- [x] `cove runner up` brings up runner container
- [ ] Runner shows online in Forgejo admin (requires live stack — manual)
- [ ] Trivial workflow executes on push (requires live stack — manual)
- [ ] Vault stretch goal (not implemented — documented as stretch in plan)