# AGENTS.md

Read **[PURPOSE.md](PURPOSE.md)** for this project's identity, worldview, and foundational principles.

## Cove-specific notes

- **`cove up` requires sudo** for `/etc/resolver/cove` and `mkcert -install`. Do not run it autonomously — ask the operator to run it, or offer to set up passwordless sudo for those specific commands via a `/etc/sudoers.d/cove` entry.
- **`cove up --no-sudo`** skips sudo tasks but DNS resolution for `*.cove` won't work without the resolver file. Use `curl -H "Host: ..." https://127.0.0.1/...` for health checks when testing without sudo.
- **Colima** is the Docker runtime on macOS. `cove up` auto-starts it if not running and switches the Docker context to `colima`.
- **`uv run --directory cli cove up`** runs the project-local CLI without reinstalling the system tool. Use this for testing changes.
- **`fj`** is the Forgejo CLI. See [docs/fj-guide.md](docs/fj-guide.md) for draft PR workflow, WIP title conventions, and Cove-specific usage rules.
