# Compose source is not namespaced: an empty `.env` collapses binds, a shared project name hijacks the stack

**Found:** 2026-10-18, incident `20261018-015539` (sev-1)
**Status:** Hardened — `cove.stateless.ensure_compose_source_ready` guards every CLI compose path, and `bringup.yml` carries a pre-flight assert. Residual risk tracked below.

## Failure mode

`resolve_compose_dir()` resolves in the order `COVE_COMPOSE_DIR`, `./compose`,
`.worktrees/<name>/compose`, git-toplevel `compose/`, `~/.config/cove/compose`.
Any of these can be a compose dir whose `.env` is missing — fresh bb git
worktrees are exactly that case, because `.env` is gitignored. When `.env` is
absent (or its `COVE_DATA_ROOT` / `FORGEJO_DATA_ROOT` is empty),
`docker compose` interpolates `${COVE_DATA_ROOT}` to the empty string, and every
bind source `${COVE_DATA_ROOT}/x` collapses to the container-absolute path `/x`.
Docker then creates that directory *inside the VM* and mounts it. The container
starts, answers health checks, and serves from the wrong storage.

Two properties compound it:

1. **Partial `.env` files are worse than absent ones.** `bringup.yml` renders
   `.env` "first boot only" (`when: not (compose_dir ~ "/.env") is exists`). A
   service `up` (e.g. `cove speedtest up` via `_upsert_env`) can write a single
   key into a dir with no rendered `.env`. The file then *exists*, so the next
   `cove up` skips the render and leaves the incomplete file in place. This is
   what produced the incident's 162-byte `SPEEDTEST_*`-only `.env`.
2. **The project name is not namespaced to the checkout.**
   `compose/docker-compose.yml` pins `name: cove`. Compose keys a project by
   (name, working directory), so any *other* compose dir declaring `name: cove` —
   a worktree, a second checkout — recreates the **live** containers. The
   offending invocation hijacked the live `cove` project.

## Why the pre-existing wedged-dir guards missed it

`bringup.yml` already had `Assert data-root bind-mount targets are not
directories` and its nginx sibling (see `docker-bindmount-auto-directory.md`).
Those stat the *Ansible* `cove_data_root` var, which is always populated
(`{{ ansible_env.HOME }}/Documents/cove-data`). They never read the compose
`.env` value that Docker Compose actually interpolates, so an empty `.env` value
was invisible to them. The two guard families are complementary: the wedged-dir
guards catch a Docker-created directory at a *correctly-resolved* path; this
guard catches an *incorrectly-resolved* path.

## Hardening applied

`cli/cove/stateless.py`:

- `effective_env_value(compose_dir, key)` / `effective_data_root` — the value
  Compose would interpolate (process env when non-empty, then `.env`).
- `require_usable_data_root` — aborts when a dir's `.env` exists but
  `COVE_DATA_ROOT` or `FORGEJO_DATA_ROOT` is unset/empty. The canonical install
  dir is exempt when its `.env` is absent (first boot).
- `declared_compose_project_name` / `require_live_project_from_canonical_dir` —
  refuses a dir that declares the live `name: cove` while pointing at a
  non-canonical data root, unless `COVE_ALLOW_FOREIGN_DATA_ROOT` is set or its
  data root *is* the canonical one.
- `ensure_compose_source_ready` — the composite entry point, called by
  `cove up`, `cove down`, `cove uninstall --all`, and every service
  `up`/`down` (ade, speedtest, toolhive, runner, litellm, tunnel).

`compose/bringup.yml`: `Assert the compose .env carries a usable COVE_DATA_ROOT`
immediately before the compose invocation, covering a direct
`ansible-playbook` run.

Tests: `cli/tests/test_compose_source_guards.py` (35 tests; the guard suites
revert red when the guards are neutered or the assert is deleted).

## Residual risk (this debt)

1. **No automated binding between `docker-compose.yml` data-root mounts and
   `REQUIRED_DATA_ROOT_KEYS`.** A new `${SOME_NEW_ROOT}/x` mount with a new key
   would not be guarded until the key is added to `REQUIRED_DATA_ROOT_KEYS`.
2. **Non-CLI compose invocations are covered only by the Ansible assert.**
   `scripts/staging/deploy-isolated.sh` calls `docker compose ... up` directly
   with its own `staging.env`; it is safe today because it writes both keys, but
   it does not share the Python guard.
3. **`.env` files with `~` in the value.** `.env.example` ships
   `COVE_DATA_ROOT=~/Documents/cove-data`, which Compose does not expand. The
   guard's regex accepts any non-empty value, so a literal `~` would pass the
   guard and then collapse to `~/Documents/cove-data/...` inside the container.
   Not a live bug (the rendered `.env` writes an absolute path), but the example
   is misleading.

## Follow-up options

- A test that parses `docker-compose.yml` for `*_DATA_ROOT` mount keys and
  asserts each is in `REQUIRED_DATA_ROOT_KEYS` (catches drift).
- Fix `.env.example` to document that `~` is not expanded.
- Route `deploy-isolated.sh` through a shared guard helper.

Related: `docker-bindmount-auto-directory.md` (the wedged-directory class this
guard complements), `extract-resources-deletes-env.md` (runtime compose dir is a
cache regenerated from the wheel).
