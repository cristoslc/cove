**Responding to:** Per operator request: implement Forgejo issue #48

Intent: Add a Forgejo Actions runner (`forgejo-runner`) to the cove stack as an optional service (profile: `runner`), following the plan at `docs/plans/forgejo-actions-runner.md`.

**Why:** Forgejo Actions workflows are inert without a registered runner. This unblocks CI.

**Success looks like:**
- `cove runner up` starts the runner container, which registers with Forgejo and shows as online
- A trivial workflow (echo) executes on push
- (stretch) workflow step reads a secret from Vault via `VAULT_TOKEN`

**Approach — 6 work units:**
1. Compose service + bringup wiring (image `data.forgejo.org/forgejo/runner:11`, profile `runner`, docker socket mount, memory limit, data volume)
2. IaC registration in `provision_forgejo.yml` (fetch registration token via admin API, register non-interactively, idempotent skip)
3. CLI: `cove runner up|down|status|logs` mirroring speedtest pattern
4. Docs (`docs/services/forgejo-runner.md`) + coverage matrix rows
5. Tests (`cli/tests/test_runner.py`) mirroring `test_speedtest.py`
6. Sync + verify (test gate green)
