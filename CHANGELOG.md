# Changelog

All notable changes to Cove are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] — 2026-07-29

### Added
- **Landing page** at `cove.local` — service portal with status indicators, links to all Cove services, config, and CA download. `cove`/`cove.local` are no longer Forgejo aliases.

### Changed
- **Primary domain migration to `*.cove.local`** — all default service URLs, CLI constants, templates, and documentation now prefer `*.cove.local` over `*.cove`. The `*.cove` domains remain as nginx aliases, cert SANs, and DNS entries for backward compatibility (Phase 4 will remove them).

## [0.2.0] — 2026-07-26

### Added
- **LiteLLM proxy service** — hardened LLM proxy with nginx route whitelisting, TLS via cove certs, optional compose profile (`litellm`), and CLI management (`cove litellm up|down|status|logs`). Accessible at `https://litellm.cove/`.
- **LiteLLM admin UI** — PostgreSQL-backed (`cove-litellm-db` container) with Prisma migrations, master-key auth, `UI_USERNAME`/`UI_PASSWORD` env vars.
- **Staging pipeline** — `scripts/staging/` (`setup.sh`, `deploy.sh`, `e2e.sh`, `teardown.sh`) for branch-to-staging deploy and E2E before merge. Tier-2 test marker (`staging`) separated from tier-1 (`e2e`).
- **Model management** — `STORE_MODEL_IN_DB` enabled for UI-based model config; Ollama Cloud providers (deepseek-v4-flash, deepseek-v4-pro, glm-5.1, glm-5.2, kimi-k2.6, kimi-k2.7-code).
- **MinIO root credential** seeded into `OP_REFS` and credential bootstrap.
- **ADR-015** (IaaS graduation test) and **ADR-016** (two-tier service adoption rubric).
- Vault CLI test coverage: 7 new tests for TLS verification and default-address behavior.

### Changed
- **Vault CLI default address** now `https://vault.cove/` (was `http://127.0.0.1:8200`, which was unreachable because the vault container's port 8200 is not published to the host). TLS verified against the cove root CA (`~/.config/cove/pki/rootCA.pem`); falls back to the system trust store if the CA file is missing.
- **LiteLLM nginx ingress** uses a variable + resolver for the upstream so an optional LiteLLM service doesn't break nginx startup.
- `PROXY_BASE_URL=https://litellm.cove` so login redirects use HTTPS.

### Fixed
- `cove creds vault-get` / `vault-put` no longer fail with `ConnectionRefusedError` — now routed through the nginx ingress at `https://vault.cove/`.
- Tailscale daemon-dead condition no longer fatal; content-hash version detection added.
- LiteLLM config mounted from cove data root (read-write, first-boot render, user-mutable).
- LiteLLM binds `0.0.0.0` inside the container; wrong-host test now expects `ConnectionError`.
- Ansible callback error suppressed; Colima/Forgejo readiness waits added.

### Known issues
- 9-10 LiteLLM tests in `tests/test_litellm.py` fail on `main` due to config drift between the compose/nginx template and the test-encoded posture (see `docs/tech-debt/litellm-test-drift.md`). Unrelated to the vault fix.

## [0.1.0] — 2026-05-07

Initial public release of the Cove CLI.

[0.3.0]: https://git.cove.local/cristos/cove/releases/tag/v0.3.0
[0.2.0]: https://git.cove.local/cristos/cove/releases/tag/v0.2.0
[0.1.0]: https://git.cove.local/cristos/cove/releases/tag/v0.1.0