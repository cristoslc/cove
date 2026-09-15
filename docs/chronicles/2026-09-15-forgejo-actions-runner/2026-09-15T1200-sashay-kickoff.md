**Responding to:** nothing (sashay kickoff for issue #48)

Sashay started for **#48 — Add Forgejo Actions runner to cove (CI currently inert)**.

Plan committed to trunk at beaa555: docs/plans/forgejo-actions-runner.md.

Key design decisions from plan + research:
- Runner ships as an **optional service** (profile `runner`), mirroring litellm/speedtest: compose service, `cove runner up|down|status|logs`, status entry.
- **No nginx route** — the runner is outbound-only (polls forgejo), unlike litellm/speedtest which needed ingress.
- **Registration is IaC**: provision_forgejo.yml mints an admin token via `docker exec ... generate-access-token` today; we reuse that path to fetch the instance-wide registration token from `/api/v1/actions/runners/registration-token` and register non-interactively, with a skip-if-registered idempotency check.
- Stretch goal: scoped Vault policy/token (`cove-runner`, read-only `secret/data/op-cache/**`) — first-of-its-kind scoped pattern; only the all-sudo `admins` policy exists.