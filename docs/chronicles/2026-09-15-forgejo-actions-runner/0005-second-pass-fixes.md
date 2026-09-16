**Responding to:** second review pass findings (3 residual)

Checkpoint: all three second-pass findings fixed in-place by orchestrator:

- Residual 1 (MEDIUM): `until: runner_reg_token.status == 200` added so `retries: 3 / delay: 5` actually engage (provision_forgejo.yml).
- Residual 2 (MEDIUM): hardened table healthcheck row corrected — healthcheck now exists (`forgejo-runner --version` process check), row changed to "Partial" with accurate description (docs/services/forgejo-runner.md).
- Residual 3 (LOW): trailing newlines appended to README.md, CHANGELOG.md, docs/architecture.md.

Sync re-run (`sync_compose_resources.py`) then verification:
- test_runner.py: 44/44 pass
- Full unit gate: **434 passed, 0 failed** (not e2e and not staging)