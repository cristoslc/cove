# AGENTS.md

Read **[PURPOSE.md](PURPOSE.md)** for this project's identity, worldview, and foundational principles.

## Cove-specific notes

- **`cove up` requires sudo** for `/etc/resolver/cove` and system trust store install. Do not run it autonomously — ask the operator to run it, or offer to set up passwordless sudo for those specific commands via a `/etc/sudoers.d/cove` entry.
- **`cove up --no-sudo`** skips sudo tasks but DNS resolution for `*.cove` won't work without the resolver file. Use `curl -H "Host: ..." https://127.0.0.1/...` for health checks when testing without sudo.
- **Colima** is the Docker runtime on macOS. `cove up` auto-starts it if not running and switches the Docker context to `colima`.
- **`uv run --directory cli cove up`** runs the project-local CLI without reinstalling the system tool. Use this for testing changes.
- **`fj`** is the Forgejo CLI. See [docs/fj-guide.md](docs/fj-guide.md) for draft PR workflow, WIP title conventions, and Cove-specific usage rules.
- **`cove litellm`** manages the optional LiteLLM proxy service (hardened LLM proxy with Headroom compression). Subcommands: `up`, `down`, `status`, `logs`. Accessible at `https://litellm.cove/` through nginx ingress. Security posture: version-pinned, nginx route-whitelisted, read-only container, env-var-only credentials. See [docs/litellm-proxy.md](docs/litellm-proxy.md).

## Reinstall the cove CLI (uv tool)

The `cove` CLI is installed as a **uv tool** (`~/.local/bin/cove`) from a wheel built out of `cli/`. The stable tool MUST always reflect the last good **released** state, never a branch under test.

**Canonical source of compose resources is `compose/` at the repo root** — NOT `cli/cove/resources/compose/` (a build-time snapshot) and NOT `~/.config/cove/compose/` (the deployed runtime copy). During a build, `cli/scripts/sync_compose_resources.py` syncs `compose/` → resources. Edit `compose/`, never the extracted copy.

- Dev/test loop (no reinstall): `uv run --directory cli cove ...`
- Test gate before any promote: `uv run --directory cli pytest -x -q -m "not e2e and not staging"`
- **Promote** (MUST be post-merge to `main`, only after the test gate is green):
  ```
  uv build --wheel --out-dir cli/dist   # from cli/
  uv tool install --force --from cli/dist/cove_cli-<ver>-py3-none-any.whl
  ```
- **Rollback** on breakage (restore the last tagged release, then re-promote):
  ```
  git checkout v<last-tag> -- cli/ compose/   # restore canonical source for the tag
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

Staging deploys the branch to the local Docker stack and runs E2E tests against `https://127.0.0.1:8443` before merge. Scripts at `scripts/staging/` (`setup.sh`, `deploy.sh`, `e2e.sh`, `teardown.sh`).
Full reference: `.agents/agents-md-detail/staging-e2e.md`.
