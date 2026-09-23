## 0.6.0 (2026-09-23)

- **`cove tunnel`** — managed public relay via zrok2 (PR #53). `cove tunnel up/ls/down/reset-token` with an interactive service picker, interactive token onboarding (1Password via ADR-017), platform-aware per-arch image pinning, Cove-rendered nginx share routes (rendered mid-stream, removed on Ctrl-C), orphan-share cleanup on `up`, clickable `?interstitial=1` links, and full Ctrl-C teardown. Docs: `docs/services/tunnel.md`.

# Changelog

All notable changes to Cove are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.1] — 2026-09-22

### Added
- **Node/Electron CA trust documentation** on the `ca.cove` config page (`/config/`) — Node.js and Electron never read the OS trust store, so TLS to `*.cove` names fails even after the OS trusts the Cove CA. The page now documents `NODE_EXTRA_CA_CERTS`, a download-first path (`curl -kL -o cove-root-ca.pem https://ca.cove/config/ca`), durable OS-store alternatives (macOS `security add-trusted-cert`, Linux `update-ca-certificates`), and the `launchctl setenv` non-durability caveat. See issue [#51](https://git.cove.local/cristos/cove/issues/51).
- **Forgejo Actions Runner service** (`cove runner up|down|status|logs`) — optional profiled CI runner that polls Forgejo for Actions workflows and executes them in Docker sibling containers. Outbound-only, no nginx route, no 1Password seed. Registration handled by `provision_forgejo.yml` IaC. See [docs/services/forgejo-runner.md](docs/services/forgejo-runner.md).
- **Forgejo webhook allowlist** (`webhook.ALLOWED_HOST_LIST`) — explicit, configurable compose env var defaulting to `loopback` (upstream default `external` blocked all loopback/private webhook delivery, breaking local receivers like tidesman). Widen per-receiver via `FORGEJO_WEBHOOK_ALLOWED_HOST_LIST=loopback,<host-or-cidr>`. See [docs/services/forgejo.md](docs/services/forgejo.md) and issue [#44](https://git.cove.local/cristos/cove/issues/44).

### Fixed
- **cryptography CVE-2026-69247** (GHSA-g6cj-pr64-35w5, Bleichenbacher oracle in `pkcs7_decrypt_*`) — dependency floor raised to `cryptography>=50.0.0` (patched release), lock resolves 50.0.1, so the pinned version cannot regress.
- **Runtime `.env` preserved across compose re-extraction** — `extract_resources()` no longer deletes the deployed `.env` on a promote (the 2026-09-02 incident: promote wiped `.env`, a bare `docker compose up` then booted Forgejo against an empty data mount). `cove up` additionally fails loud before bringup if `docker compose config` reports unset `*_DATA_ROOT` variables. See `docs/tech-debt/extract-resources-deletes-env.md`.
- **Bringup bind-mount dir guard** — bringup fails loudly if Docker auto-created directories at file-mount targets.

## [0.5.0] — 2026-08-14

### Added
- **`cove status` shows stopped optional services** — status output no longer hides profiled optionals; `cove up` reconciles the running ones. Stopped optionals no longer fail the status exit code.

### Fixed
- **`cove up` BECOME password prompted once** — not once per playbook.
- **Speedtest Tracker admin env re-injected on re-run**; `DISPLAY_TIMEZONE` set. `APP_KEY` no longer clobbered; Cove Admin secrets pulled in one batch.

## [0.4.1] — 2026-08-12

### Fixed
- **idna Dependabot vulnerability** (GHSA-65pc-fj4g-8rjx, CVSS 5.3) — bumped transitive `idna` to `>=3.15` (resolves to 3.18) and added an explicit `idna>=3.15` constraint to `cli/pyproject.toml` as a regression guard.

## [0.4.0] — 2026-08-12

### Added
- **Speedtest Tracker service** (`cove speedtest up|down|status|logs`) — optional profiled service monitoring the operator's WAN link (uptime, latency, download/upload bandwidth, jitter, packet loss) via scheduled Ookla `speedtest` CLI runs. Accessible at `https://speedtest.cove/` through nginx ingress. Default schedule: 8 daytime runs (`0 7,9,11,13,15,17,19,21 * * *`).
- **IaC provisioning** for Speedtest Tracker — admin email/password sourced from the shared **`Cove Admin`** 1Password item (keyed to `https://cove.local/`, ADR-017); APP_KEY in the `Speedtest Tracker` item (keyed to `https://speedtest.cove.local/`); fail-loud if the Cove Admin item is missing.
- **ADR-017** — Unified Cove Admin Identity: all Cove services share the `admin@cove.local` identity.
- **Cove Pages portal** — `pages.cove` autoindex portal listing owners/sites, plus an autoindex JSON API.
- **nginx auto-reload** — `cove up` re-renders the nginx config and auto-reloads via a handler.

### Changed
- **IaC bias codified in AGENTS.md** — the `cove` wheel is the single self-contained source of truth for compose; reinstalling `cove` pulls updated compose; no runtime files outside the install.
- **Docker Compose `--profile` flag ordering** fixed — `--profile` must precede the subcommand (Docker Compose 5.4.0); `cove speedtest up` / `cove litellm up` corrected.
- **Vault double-slash URL** fixed — `vault_cache.py` and `vault_unseal.py` no longer build `https://vault.cove.local//v1/...` (Vault returned 404).

### Fixed
- Speedtest APP_KEY format (`base64:` prefix required by Laravel).
- Speedtest `.env` created with 0600 mode (was world-readable on fresh creation).

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

[0.5.1]: https://git.cove.local/cristos/cove/releases/tag/v0.5.1
[0.5.0]: https://git.cove.local/cristos/cove/releases/tag/v0.5.0
[0.4.1]: https://git.cove.local/cristos/cove/releases/tag/v0.4.1
[0.3.0]: https://git.cove.local/cristos/cove/releases/tag/v0.3.0
[0.2.0]: https://git.cove.local/cristos/cove/releases/tag/v0.2.0
[0.1.0]: https://git.cove.local/cristos/cove/releases/tag/v0.1.0
