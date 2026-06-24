# AGENTS.md

Read **[PURPOSE.md](PURPOSE.md)** for this project's identity, worldview, and foundational principles.

## Cove-specific notes

- **`cove up` requires sudo** for `/etc/resolver/cove` and `mkcert -install`. Do not run it autonomously — ask the operator to run it, or offer to set up passwordless sudo for those specific commands via a `/etc/sudoers.d/cove` entry.
- **`cove up --no-sudo`** skips sudo tasks but DNS resolution for `*.cove` won't work without the resolver file. Use `curl -H "Host: ..." https://127.0.0.1/...` for health checks when testing without sudo.
- **Colima** is the Docker runtime on macOS. `cove up` auto-starts it if not running and switches the Docker context to `colima`.
- **`uv run --directory cli cove up`** runs the project-local CLI without reinstalling the system tool. Use this for testing changes.
- **`fj`** is the Forgejo CLI. See [docs/fj-guide.md](docs/fj-guide.md) for draft PR workflow, WIP title conventions, and Cove-specific usage rules.

## Test command

`uv run --directory cli pytest tests/ -q`

## Operator-assisted E2E exemption

Cove is a local-only developer platform with no remote operator surface. The test suite includes e2e tests (`tests/test_e2e_dns.py`, `tests/test_e2e.py`) that exercise the live stack via `cove up --no-sudo` in the worktree. Operator-assisted E2E tests under `test/operator-e2e/` are not applicable — the staging scripts at `scripts/staging/` serve the equivalent role for this project.
