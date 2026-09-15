**Responding to:** code-review findings (chronicle 0003), fixes dispatched to implementation subagent

Checkpoint: all review findings addressed in commit 482eba4. Fixes verified:

- H1: `no_log: true` added to register task (provision_forgejo.yml)
- H2: data volume now `${COVE_DATA_ROOT:-/data}/forgejo-runner:/data`; `FORGEJO_RUNNER_DATA_ROOT` removed from compose + bringup .env render; phantom `forgejo_runner_data_root` var dropped (M12 covered)
- H3: dead `_compose_dir`/`_compose_env_path`/`_upsert_env` deleted from runner.py
- H4: admin URL fixed (`/-/admin` → `/admin`)
- H5: Mermaid edge corrected (R→F); Docker daemon node moved out of Cove Stack subgraph; Forgejo node relabeled `forgejo:3000 internal`
- M1: `cove runner status|logs` now target the `forgejo-runner` service
- M2: container name templated with `forgejo_runner_container_name | default(...)`; ps filter anchored
- M3: token fetch got `status_code: 200` + retries (3 × 5s)
- M4: guard switched to `is not skipped`
- M5: summary claim gated on registration check or register rc
- M6: `changed_when: true`
- M7: hardened/NOT-hardened table added; pages mount documented as inert; trust model stated
- M8: Quick Start rewritten (two-command flow, restart-loop caveat)
- M9: README services table + docs list, AGENTS.md note, CHANGELOG [Unreleased], architecture.md inventory updated
- M10: trailing newlines added
- M11: duplicate port test dropped
- L1: healthcheck added to forgejo-runner service
- L2: runner data dir task separated with mode 0700
- L3: test imports hoisted to module top

**Test results: 434 passed, 0 failed** (unit gate `not e2e and not staging`, up from 422 — new tests for status/logs targeting).

Deliberately not done (rationale): conftest timeout kept (chronicle 0002); job-label digests and config.yml/valid_volumes wiring documented as future hardening; Vault stretch deferred.