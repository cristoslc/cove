# Parley: What uvx Doesn't Solve

**Topic:** System dependencies that `uvx cove` can't eliminate
**Source:** `docs/musings/cove-repo-fair.md` — "What uvx doesn't solve" section
**Date:** 2026-06-25

## Opening position

The musing lists four things uvx doesn't solve — sudo, Docker, Ansible, mkcert — and dismisses them as "system-dependency questions that apply equally to pip install and uvx." I think this is wrong. The whole point of `uvx` is zero ceremony. If `uvx cove up` fails with "install Docker first," that's a broken promise. The question is which of these Cove can actually solve and which are genuinely irreducible.

## Tension backlog

1. **sudo** — `/etc/resolver/cove` and `mkcert -install` need root. Can Cove eliminate the sudo requirement entirely, or is this irreducible?
2. **Docker/Colima** — heaviest prerequisite. Can Cove use an alternative runtime?
3. **Ansible** — ~30MB to vendor. Worth it?
4. **mkcert** — single Go binary per platform. Worth vendoring?

## Resolved tensions

### 1. sudo — irreducible for now

**Resolution:** `/etc/resolver/cove` and hosts edits both require root on macOS. No way around it without a kernel-level change or a third-party DNS resolver that doesn't use the system resolver chain. `cove up --no-sudo` is the honest escape hatch — DNS won't resolve, but the harbor is reachable by IP. Accept this as irreducible for the `uvx` target. The `cove up` output should tell the user what they're missing.

### 2. Docker/Colima — irreducible, prereq check

**Resolution:** Docker Compose is the architecture. Podman is a potential alternative but adds a second runtime to support. On macOS, Colima is the only realistic path. Cove already auto-starts Colima and switches the Docker context. The remaining gap is installation — `brew install colima` is one manual step. Accept as irreducible. Add a prereq check in `cove up` that verifies Docker CLI is available and meets a minimum compatible version. Fail early with a clear install message.

### 3. Ansible — add as Python dependency

**Resolution:** Add `ansible-core` to `pyproject.toml` dependencies. Not vendoring — just declaring a PyPI dependency that pip/uv installs normally. No license issue (GPL-3.0 dependency doesn't affect Cove's license). Eliminates a host prerequisite and version-mismatch failures. ~30MB download on first install, cached by uv.

### 4. mkcert — replace with Python cryptography (future sashay)

**Resolution:** Replace mkcert with a Python module using `cryptography` to generate the root CA. The install step still needs sudo (system trust store is root-owned), same as mkcert. This warrants its own spike/sashay with a thorough test suite to ensure it functions as well as mkcert. Not part of the initial `uvx` push.
