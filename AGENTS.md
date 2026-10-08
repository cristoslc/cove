# AGENTS.md

Read **[PURPOSE.md](PURPOSE.md)** for this project's identity, worldview, and foundational principles.

## Cove-specific notes

- **`cove up` requires sudo** for `/etc/resolver/cove` and system trust store install. Passwordless sudo is toggled with `cove sudo enable` (installs a validated `/etc/sudoers.d/cove` drop-in after one sudo prompt; `setup` remains as a hidden alias), `cove sudo status` checks it, and `cove sudo disable` removes it. With the drop-in installed, `cove up` runs with no BECOME prompt. Until it is installed on a machine, do not run `cove up` autonomously — ask the operator to run it.
- **`cove up --no-sudo`** skips sudo tasks but DNS resolution for `*.cove` won't work without the resolver file. Use `curl -H "Host: ..." https://127.0.0.1/...` for health checks when testing without sudo.
- **Colima** is the Docker runtime on macOS. `cove up` auto-starts it if not running and switches the Docker context to `colima`.
- **`uv run --directory cli cove up`** runs the project-local CLI without reinstalling the system tool. Use this for testing changes.
- **`fj`** is the Forgejo CLI. See [docs/guides/fj-guide.md](docs/guides/fj-guide.md) for draft PR workflow, WIP title conventions, and Cove-specific usage rules.
- **`cove litellm`** manages the optional LiteLLM proxy service (hardened LLM proxy with Headroom compression). Subcommands: `up`, `down`, `status`, `logs`. Accessible at `https://litellm.cove/` through nginx ingress. Security posture: version-pinned, nginx route-whitelisted, read-only container, env-var-only credentials. See [docs/services/litellm-proxy.md](docs/services/litellm-proxy.md).
- **`cove speedtest`** manages the optional Speedtest Tracker service (WAN-link monitor). Subcommands: `up`, `down`, `status`, `logs`. Accessible at `https://speedtest.cove/` through nginx ingress. The admin identity comes from the shared **`Cove Admin`** 1Password item (keyed to `https://cove.local/`, ADR-017); the APP_KEY lives in the `Speedtest Tracker` item keyed to `https://speedtest.cove.local/`. Both reused across all machines. See [docs/services/speedtest.md](docs/services/speedtest.md).
- **`cove toolhive`** manages the optional ToolHive MCP gateway service (MCP gateway at `mcp.cove`; the only MCP surface in Cove — LiteLLM MCP stays disabled, CVE-2026-42271). Subcommands: `up`, `down`, `status`, `logs`. Accessible at `https://mcp.cove/` through nginx ingress; the API/UI binds `127.0.0.1` only (loopback). The docker socket is mounted read-only; MCP servers run as sibling containers constrained by permission profiles and explicit mounts. The curated registry is IaC (`compose/toolhive/registry.json`, mounted read-only, remote fetch off). See [docs/services/toolhive.md](docs/services/toolhive.md).
- **`cove runner`** manages the optional Forgejo Actions Runner (CI runner). Subcommands: `up`, `down`, `status`, `logs`. No ingress URL (outbound-only service). Registration is IaC: `cove runner up` starts the container but does NOT register; `cove up` with the runner profile active registers it. See [docs/services/forgejo-runner.md](docs/services/forgejo-runner.md).
- **`cove ade`** manages the ADE bb server (agentic harness, core service since 0.8.0 — `cove up` starts it). Subcommands: `up`, `down`, `status`, `logs`. Accessible at `https://ade.cove/` through nginx with WebSocket upgrade. Runs pinned `bb-app` (build arg `ADE_BB_APP_VERSION`), data under `${cove_data_root}/ade/`, bound `0.0.0.0` inside the container. Direct-URL mode is unauthenticated by design — the Cove network is the trust boundary. `cove ade down` stops it until the next `cove up`. Enrolling the Mac as machine #1 is the Phase 2 cutover (runbook in docs). See [docs/services/ade.md](docs/services/ade.md).

## IaC bias

Cove is **infrastructure-as-code first**. Every service's configuration, credentials, and runtime state MUST be declared in code (compose, bringup.yml, seeds, CLI provisioning) — never configured by hand in a running container or via ad-hoc UI clicks. Concretely:

- **Admin users / credentials** are provisioned from 1Password (via `cove creds` + shared items) and injected into the compose `.env`, so a fresh deploy seeds the correct identity — never the app's default (e.g. `admin@example.com`).
- **Schedules / defaults** (e.g. a speedtest schedule) are declared in compose with sensible defaults, so the service is functional without manual setup.
- **Manual fixes to a running container are a smell** — if you find yourself editing a DB or config by hand, that change belongs in code (compose env, seed, or CLI provisioning) and a test.
- See ADR-017 (Unified Cove Admin Identity) for the shared-identity convention.

- **nginx config is generated**: `compose/nginx/default.conf` is a rendered artifact, gitignored, regenerated unconditionally by `bringup.yml` (template `default.conf.j2`). NEVER edit `default.conf` — it will be overwritten on the next `cove up`. Always edit `default.conf.j2`; `cove up` re-renders it and auto-reloads nginx via a handler.

## The cove CLI is the single source of truth

**`cove` (the installed uv tool) is the single, self-contained source of truth for the entire Cove platform.** It bundles ALL compose resources (compose files, bringup.yml, seeds, nginx templates, certs) inside the wheel. Reinstalling `cove` pulls updated compose files. **No runtime files should exist outside the cove install** — the deployed compose dir (`~/.config/cove/compose/`) and the running stack's `.env` are runtime copies regenerated from the wheel, never hand-edited.

The repo's `compose/` at the root is the **dev-time source** that gets synced INTO the wheel at build time (via `cli/scripts/sync_compose_resources.py`). It is NOT the runtime source of truth — the wheel is. A change to `compose/` only takes effect after the wheel is rebuilt and `cove` reinstalled.

**Consequence:** any change to compose (services, schedules, defaults, credentials) requires a **reinstall** of `cove` to propagate. There is no separate "deploy the compose change" step — reinstalling `cove` IS the deploy.

## Reinstall the cove CLI (uv tool)

The `cove` CLI is installed as a **uv tool** (`~/.local/bin/cove`) from a wheel built out of `cli/`. The stable tool MUST always reflect the last good **released** state, never a branch under test.

- Dev/test loop (no reinstall): `uv run --directory cli cove ...`
- Test gate before any promote: `uv run --directory cli pytest -x -q -m "not e2e and not staging"`
- **Promote** (MUST be post-merge to `main`, only after the test gate is green):
  ```
  python3 cli/scripts/sync_compose_resources.py   # sync compose/ -> bundled resources
  uv build --wheel --out-dir cli/dist             # from cli/
  uv tool install --force --from cli/dist/cove_cli-<ver>-py3-none-any.whl
  ```
- **Publish — BOTH hosts, always.** A release is not cut until it exists on
  **GitHub** (`github` remote, the public install path) AND **Forgejo**
  (`origin`, git.cove), each with the wheel attached and notes from its
  CHANGELOG section. Canonical command after tagging:
  ```
  scripts/release.sh <ver>      # pushes tag to origin+github, publishes both hosts, idempotent
  ```
  The Forgejo host is LAN-only, so GitHub-hosted runners cannot publish there —
  `.github/workflows/release.yml` covers the GitHub side on tag push, while the
  Forgejo half always goes through `scripts/release.sh` from the operator's
  machine. See docs/tech-debt/dual-host-release-drift.md (the 2026-09-28 drift
  this rule closes: GitHub releases had stopped at v0.5.0).
- **Rollback** on breakage (restore the last tagged release, then re-promote):
  ```
  git checkout v<last-tag> -- cli/ compose/   # restore canonical source for the tag
  python3 cli/scripts/sync_compose_resources.py
  uv build --wheel --out-dir cli/dist         # from cli/
  uv tool install --force --from cli/dist/cove_cli-<ver>-py3-none-any.whl
  ```
- **Sashay-aware:** the promote step is a post-merge *release* action, not a trunk action. During a sashay or while a branch is under test, NEVER reinstall the stable `cove` tool from a branch wheel. Use `uv run --directory cli` for branch behavior; the staging test harness already builds the wheel into an isolated venv for tier-2 staging tests.

## Test command

```
uv run --directory cli pytest -x -q -m "not e2e and not staging"
```

## Test command (integration)

```
uv run --directory cli pytest -x -q -m "e2e and not staging"
```

## Test command (staging)

```
uv run --directory cli pytest -x -q -m staging
```

Invoked via `scripts/staging/e2e.sh` against the deployed staging stack.

## Test coverage matrix

Master coverage matrix: `docs/test-coverage-matrix.yaml`

## Staging E2E

Staging runs the branch as an **isolated** Docker Compose project (`-p cove-staging`, nginx on `https://127.0.0.1:9443`) — the live stack is never re-rendered or restarted. Scripts: `scripts/staging/deploy-isolated.sh` (deploy), `e2e.sh` (tier 2 tests), `teardown.sh` (compose down -v + staging data removal). The legacy in-live mode (`deploy.sh`, port 443 since the pf shim was dropped) still exists but re-renders live nginx and restarts live containers; use it only deliberately.
Full reference: `.agents/agents-md-detail/staging-e2e.md`.
