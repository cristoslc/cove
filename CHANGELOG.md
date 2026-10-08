# Changelog

All notable changes to Cove are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 0.12.0 (2026-10-08)

### Changed
- **nginx owns port 443 directly — the pf 443→8443 shim is gone** — compose now publishes `0.0.0.0:443:443` (nginx was already listening on 443 inside the container; only the host facing port was wrong). Bringup no longer installs a macOS pf redirect for `localhost:443 → 8443` on every `cove up`, and no longer wires a `tailscale serve` listener on 443. `NGINX_HTTPS_PORT` is removed from `.env`/Ansible; the single source of truth is `cove.constants.NGINX_HTTPS_PORT = 443`, re-exported by `cove.status`. All CLI probes (`cove status`, `cove litellm status`, `cove speedtest status`, `cove toolhive status`) go through nginx via that constant — nothing in the CLI hardcodes 8443 anymore. Contract tests pin the compose publish, the port coupling points, and that `scripts/staging/*` no longer reference 8443; the legacy in-live staging default moves to `https://127.0.0.1:443`. Rationale: pf rules do not survive reboot and silently failed (`failed_when: false`), so `https://git.cove/` and friends were unreachable from the browser even while `cove status` (probing 8443 directly) reported green. This lands the reviewed sashay `drop-pf-shim-nginx-owns-443` (Forgejo chronicle 2026-09-19; three review rounds converged, approved).

## 0.11.1 (2026-10-08)

### Fixed
- **ToolHive never started: the curated registry was mounted as a file into a directory that does not exist** — 0.11.0's compose bind-mounted `registry.json` straight to `/registry/registry.json`, but the distroless `thv` rootfs (v0.51.4) ships no `/registry` directory and Docker cannot create one for file→file binds, so the container exited 127 with a "not a directory" mount error. The mount is now a directory bind (`${COVE_DATA_ROOT}/toolhive:/registry:ro`; Docker creates the destination and the seed file appears at `/registry/registry.json`), and bringup's render task re-runs when the seed file is missing or when `thv`'s persisted config has blanked `local_registry_path` (a second way the curated registry went dark). Contract tests updated to the directory-bind shape.
- **bringup forced Colima on macOS, resurrecting the VM behind the operator's back** — every `cove up` ran `colima start` + `docker context use colima` unconditionally, re-pinning the engine to Colima and rewriting the Docker context in `~/.docker/config.json`. Bringup now probes `docker info` first: an answerable daemon wins as-is, Colima is only started as a fallback when no engine responds.
- **forgejo-runner and toolhive restart-looped on non-Colima engines** — the compose env hardcoded Colima's docker.sock group id (991), while OrbStack's socket is `root:root` (gid 0), so gid-filtered access failed. Bringup now detects the live daemon's in-VM socket gid (scratch `stat` container) and syncs `FORGEJO_RUNNER_DOCKER_GID` / `TOOLHIVE_DOCKER_GID` into `.env` on every `cove up`. Two bringup contract tests pin the manifest.

## 0.11.0 (2026-10-02)

### Added
- **`cove sudo disable`** — removes `/etc/sudoers.d/cove` so `cove up` prompts for the BECOME password again. Prompt-free when passwordless sudo is already in place (or running as root); one sudo password prompt otherwise. After removal the functional check runs again, so the reported state is the truth even if some other `NOPASSWD: ALL` grant exists outside the cove drop-in (it says so and points at `sudo -l` rather than claiming success). Fails loud if the removal itself fails. Complements the retire-the-grant direction in `docs/musings/cove-up-sudo-friction.md`.

### Changed
- **`cove sudo enable` replaces `cove sudo setup`** — the sudo group is now a true toggle triad (`enable` / `disable` / `status`), matching the repeatable on/off reality instead of one-time-provisioning framing. `setup` remains as a hidden alias with identical behavior for existing references and muscle memory; status remediation messages, help texts, and the repo AGENTS.md now point at `enable`. Folded into 0.11.0 before its first tag, so no released version changes shape.

## 0.10.1 (2026-10-02)

### Fixed
- **`cove sudo status` could never report the drop-in installed** — the check ran `visudo -c -f /etc/sudoers.d/cove` unprivileged, but the drop-in is root:wheel 0440, so visudo always failed with EACCES and `cove up` prompted for the BECOME password even after a successful `cove sudo setup`. The check is now functional: `sudo -n -l` (never prompts, mutates nothing) must list a `NOPASSWD: ALL` grant; the listing is parsed, not just the exit code, so a recently cached sudo timestamp cannot fake a pass.
- **`sudo cove sudo setup` installed the grant for root** — under sudo, `getpass.getuser()` returns root, so the rendered drop-in granted root `NOPASSWD: ALL` and silently dropped the operator's grant (the reason `cove up` re-prompted after a root-run setup). Setup now targets `SUDO_USER`, skips the password prompt when already root, and echoes the grant target.
- **A typed BECOME password never reached sudo** — `cove up` set `ANSIBLE_BECOME_PASSWORD`, which matches no ansible-core setting; the sudo become plugin reads `ANSIBLE_BECOME_PASS` (ansible/plugins/become/sudo.py), so sudo ran with empty stdin and every become task died with `sudo: a password is required` even with the correct password typed. The env var is renamed on both the prompt and passwordless paths (an empty value stays falsy to the plugin, so no password is handed to sudo under the drop-in).

## 0.10.0 (2026-09-28)

### Added
- **ToolHive MCP gateway (`cove toolhive`)** — optional `mcp` profile service at `https://mcp.cove/`; Cove's only MCP surface (LiteLLM's MCP endpoints stay disabled for CVE-2026-42271). One pinned `thv` control-plane container (read-only docker.sock, loopback-bound UI/API) manages sibling MCP-server containers constrained by permission profiles and explicit mounts; curated IaC registry (`compose/toolhive/registry.json`: filesystem/fetch/time seed servers, tag-pinned, remote fetch off for offline-first); nginx vhost returns 403 for everything except exact-match `/health` (private-range ACL) — the UI/API route opens in Phase 2 behind an auth layer. `cove toolhive up|down|status|logs`, `cove up --all` includes it; staging E2E (`deploy-isolated.sh` profile wiring, tier-2 auth-posture tests, teardown profile guard). Docs: `docs/services/toolhive.md`; plan: `docs/plans/toolhive-mcp-gateway.md` (Forgejo PR #59).

## 0.9.1 (2026-09-28)

### Fixed
- **`cove up` failed at the nginx reload handler after a template re-render** — `open() "/etc/nginx/conf.d/default.conf" failed (2: No such file or directory)`. On macOS/Colima, file bind-mounts pin the host inode at container creation, and bringup's `template`/`copy` renders are atomic (rename → new inode), so the running cove-nginx mount served a stale inode (link-count 0) and `nginx -s reload` — which re-opens every config file — died with ENOENT, killing `cove up` at the handler flush. The handler now restarts the container (re-resolves the bind by path, ~1s blip) instead of exec-reloading; a bringup structure test pins the contract. Live-stack remediation: `docker restart cove-nginx`.

### Added
- **Tech-debt note on dual-host release drift** — `docs/tech-debt/dual-host-release-drift.md`: releases must exist on both GitHub and Forgejo (tags/releases/wheels currently diverge between the hosts; the stale goreleaser workflow can only fail); fix shape for automated dual-host publishing. v0.9.1 is the first release cut manually on both hosts as the stopgap.

## 0.9.0 (2026-09-26)

### Added
- **`cove up --all`** — launches every optional service along with the default ones. The bringup pod starts Runner with the core services (ADE is core since 0.8.0); the LiteLLM and Speedtest flows run right after the provisioning chain, so their 1Password/Vault credentials are prepared before their containers start (Vault must be up for `vault-get`/`vault-put`). The tunnel stays out — shares are created interactively with `cove tunnel up`. A credential failure on one optional service is reported without aborting the bringup (optional stays optional, same contract as `cove status`).

## 0.8.0 (2026-09-25)

### Changed
- **ADE is a core service** — `cove up` now starts the ADE bb server by default; no `cove ade up` second step (operator decision, ADR-018 day-one intent: "bb as the default harness, the way Vault is the default vault"). The `ade` compose profile is gone; a stopped ADE fails `cove status` like any core service; `cove ade down` stops it until the next `cove up`. `cove ade up` remains and is now service-scoped (`docker compose up -d --build ade`). First `cove up` after upgrade builds the ADE image (a few minutes).
- **bb-app pin 0.43.4 → 0.44.0** — aligned with the operator's installed bb. Load-bearing for Phase 2 enrollment: bb machines install the server's own tarball (`/install/bb-app.tgz`) and a daemon never auto-downgrades to an older server protocol.

### Added
- **Phase 2 cutover runbook** — `docs/services/ade.md` (Machines): migrate `~/.bb` into the container volume, quit bb, enroll the Mac's daemon via `bb machine enroll --bootstrap-file` (bootstrap from `ade.cove` → Settings → Machines). Enrollment remains an explicit operator step — it stops the host bb server.

## 0.7.1 (2026-09-25)

### Fixed
- **`cove up` failed on existing deployments after the 0.7.0 promote** — `MISSING: ade.cove` at TLS-cert validation. The cert task's `creates:` guard skipped the (already drift-aware) `cove certs sign` on machines whose cert predated ADE Phase 1, leaving validation no healing path. The sign task now runs on every `cove up`: `sign_cert` regenerates when the requested SAN set diverges from the installed cert and settles idempotent otherwise; the regenerated leaf triggers an nginx reload (notify), and the fail-loud validation remains the safety net. Two deeper fixes surfaced: the SAN comparison never matched IP entries (requested strings vs parsed `IPv4Address` objects — every real SAN list regenerated forever until normalized), and `cove certs sign` printed `Signed:` unconditionally, so Ansible could not distinguish changed from skipped (`Up-to-date:` added; bringup's `changed_when` keys off it). Validation's host list is now parity-checked against the sign argv in tests so the two can never silently diverge again.
- **`cove --version` drift** (shipped in 0.7.0) — version now read from package metadata instead of a hardcoded literal.

## 0.7.0 (2026-09-25)

- **ADE — Agentic Development Environment, Phase 1** (`cove ade`, PR #55, ADR-018) — the pinned `bb-app` server as an optional profiled service (`cove ade up|down|status|logs`), served at `https://ade.cove/` through nginx with WebSocket upgrade support and an ingress allow-list (loopback, private ranges, tailnet CGNAT; public internet denied). Data under `${cove_data_root}/ade/`; the port has a single source of truth (`ade_port`, threaded through the compose env, the container healthcheck, and the nginx upstream). Staging E2E now runs as an isolated compose project (`cove-staging`, nginx on 127.0.0.1:9443) so branch E2E no longer disturbs the live stack. See [docs/services/ade.md](docs/services/ade.md).

## 0.6.0 (2026-09-23)

- **`cove tunnel`** — managed public relay via zrok2 (PR #53). `cove tunnel up/ls/down/reset-token` with an interactive service picker, interactive token onboarding (1Password via ADR-017), platform-aware per-arch image pinning, Cove-rendered nginx share routes (rendered mid-stream, removed on Ctrl-C), orphan-share cleanup on `up`, clickable `?interstitial=1` links, and full Ctrl-C teardown. Docs: `docs/services/tunnel.md`.

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
