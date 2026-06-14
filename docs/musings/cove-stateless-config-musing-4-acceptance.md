# Musing 4 — Acceptance Criteria

The mechanism is clear. Now: what does "it works" actually mean? I want every criterion to be falsifiable — a test or a manual check that returns pass/fail. No hand-waving.

## Categories of acceptance

1. **Repo cleanliness** — no PII in tracked files
2. **Packaging** — `uv tool install cove-cli` ships the resources
3. **Init** — `cove init` works idempotently
4. **Up** — `cove up` works in installed mode without a repo
5. **Up** — `cove up` works in dev mode unchanged
6. **Resolution** — the resolver picks the right compose dir in all cases
7. **Templates** — Jinja2 templates render correctly with PII-free defaults
8. **User state** — host_vars overlay works
9. **Upgrade** — version mismatch triggers re-extraction
10. **Teardown** — uninstall cleanly removes what it should
11. **Tests** — automated test coverage
12. **Failure modes** — every error path produces a useful message

I'll write a test or check for each. If a criterion doesn't have a check, it's not really an acceptance criterion — it's an aspiration.

## 1. Repo cleanliness

### 1.1 No machine-specific usernames in tracked files

**Check:** `git grep -nE "(cristos|admin_username|admin_email)" -- ':!*.pyc' ':!__pycache__' ':!docs/musings/' ':!docs/plans/'` returns zero hits in non-doc, non-binary files.

**What stays in docs:** the musings and plans discussing the migration can mention "cristos" as a placeholder. The doc itself isn't shipped config.

**What goes:** every `admin_username: cristos` in `group_vars/all.yml`, every mention of `lc.cristos@gmail.com`, every sudoers file with the username.

### 1.2 No Tailscale FQDN in tracked files

**Check:** `git grep "taila90e7.ts.net"` returns zero hits in non-doc, non-binary files.

**What stays:** none. The Tailscale FQDN is per-host. It goes in the user's `host_vars/<hostname>.yml`.

**What goes:** `compose/dnsmasq/cove.conf` (rendered), `compose/files/actions/*/action.yml` (default `COVE_FQDN`).

### 1.3 No hardcoded hostname in tracked files

**Check:** `git grep "MBPBK-202602"` returns zero hits in non-doc, non-binary files.

**What stays:** none.

**What goes:** `compose/host_vars/MBPBK-202602.yml` (the file itself, not just the contents).

### 1.4 No rendered output in tracked files

**Check:** `git ls-files | grep -E "(default\.conf$|cove\.conf$|\.env$)"` returns zero hits.

**What stays:** `.j2` templates and `.example` files.

**What goes:** rendered `.env`, rendered nginx.conf, rendered dnsmasq.conf. These go in `~/.config/cove/compose/` (in installed mode) or stay gitignored in the repo (in dev mode).

### 1.5 No PII in `__pycache__/` or other compiled artifacts

**Check:** `git ls-files | grep -E "__pycache__|\.pyc$"` returns zero hits.

**Status:** should already be gitignored. Verify.

## 2. Packaging

### 2.1 `cli/cove/resources/compose/` is a complete copy of `compose/`

**Check:** `diff -r compose/ cli/cove/resources/compose/` (excluding rendered files) returns zero differences.

**Implementation:** a `make sync-resources` (or `cli/scripts/sync_compose_resources.py`) that does this copy. Run as part of `uv build` or as a pre-publish check.

### 2.2 `pyproject.toml` declares the resource

**Check:** `grep -A 2 "tool.setuptools.package-data" cli/pyproject.toml` shows `"cove.resources" = ["**/*"]`.

### 2.3 The built wheel contains the resources

**Check:** `uv build` produces a wheel; `unzip -l dist/cove_cli-*.whl | grep "cove/resources/compose"` shows the expected files.

### 2.4 `importlib.resources` can read the resources from an installed package

**Check:** `uv tool install .` then `python -c "from importlib.resources import files; print(list(files('cove.resources.compose').iterdir()))"` shows the compose tree.

## 3. Init

### 3.1 First `cove init` extracts resources

**Check:** With a clean `~/.config/cove/`:
- `cove init` exits 0
- `~/.config/cove/compose/inventory.yml` exists
- `~/.config/cove/compose/.version` contains the current cove-cli version
- `~/.config/cove/compose/docker-compose.yml` exists
- `~/.config/cove/compose/bringup.yml` exists
- `~/.config/cove/state/hosts/<hostname>.yml` exists (if `cove init` creates it; else `cove up` does)

### 3.2 Second `cove init` is a no-op (when versions match)

**Check:** After 3.1, run `cove init` again. Exits 0. No changes to the filesystem. Stdout: "Already initialized at version X.Y.Z."

### 3.3 `cove init --force` re-extracts

**Check:** Modify a file in `~/.config/cove/compose/`. Run `cove init --force`. The file is restored to the package resource content.

### 3.4 `cove init --force` preserves `~/.config/cove/state/`

**Check:** Create a file in `~/.config/cove/state/`. Run `cove init --force`. The file is still there.

### 3.5 `cove init` installs missing Ansible collections

**Check:** With a clean `~/.ansible/collections/`, run `cove init`. `community.docker` collection is installed. Subsequent runs are no-ops.

### 3.6 `cove init` errors if Ansible is missing

**Check:** With `ansible-playbook` not on PATH, run `cove init`. Exits non-zero with "Install: brew install ansible".

### 3.7 `cove init` errors if `cove-data` parent doesn't exist

**Check:** This is borderline — the parent (`~/Documents`) almost always exists. If we want to be safe, `cove init` checks and errors with a clear message. For now, defer — the bringup playbook creates the directories.

## 4. Up (installed mode)

### 4.1 `cove up` works from any directory on a clean host

**Setup:** clean `~/.config/cove/`, no cove-data, host prereqs met (Ansible, Colima, mkcert), Tailscale not running.

**Check:** `cd /tmp && cove up` exits 0. Containers are up. https://git.cove/ returns 200. https://vault.cove/ returns 200 (or 472 if not yet unsealed). Forgejo provisioning runs to completion.

**Sub-checks:**
- Colima is auto-started if not running
- mkcert CA is installed if not already
- TLS cert is generated for `*.cove` and all required hostnames
- /etc/hosts is updated (with sudo)
- pf NAT rule is configured (with sudo)
- Data directories are created at `~/Documents/cove-data/`
- `compose/.env` is rendered into `~/.config/cove/compose/.env`
- nginx config is rendered into `~/.config/cove/compose/nginx/default.conf`
- dnsmasq config is rendered into `~/.config/cove/state/rendered/...` or wherever
- Forgejo container starts and is healthy
- Vault container starts and is healthy
- nginx container starts and is healthy
- dnsmasq container starts and is healthy
- Vault is bootstrapped (initialized + unsealed)
- Vault user is provisioned
- Forgejo admin user is created

### 4.2 `cove up` is idempotent

**Check:** After 4.1, run `cove up` again. Exits 0. No containers are recreated (or: only those that need recreating). Forgejo admin user is not duplicated (provisioning is idempotent).

### 4.3 `cove up --no-provision` skips provisioning

**Check:** After 4.1, run `cove up --no-provision`. Containers are restarted (or not, if already up) but Vault and Forgejo provisioning playbooks are NOT run.

### 4.4 `cove up --no-sudo` skips sudo-requiring tasks

**Check:** `cove up --no-sudo` works if /etc/hosts already has the entries AND pf NAT rule is already configured. Errors clearly if either is missing.

### 4.5 `cove up` with Tailscale active uses the tailscale FQDN

**Check:** With Tailscale running, `cove up` configures `ts_dns_name` from `tailscale status --json`. The /etc/hosts entry points the tailscale name to 127.0.0.1. `tailscale serve` is configured to forward 443 → 8443.

### 4.6 `cove up` writes ansible logs when `--log` is passed

**Check:** `cove up --log` writes a log file to `~/.local/share/cove/logs/`. The log contains ansible-playbook output.

## 5. Up (dev mode)

### 5.1 `uv run --directory cli cove up` from the repo works

**Check:** From the repo root, `uv run --directory cli cove up` (or the equivalent) brings up cove using the repo's `compose/` directory. No `~/.config/cove/compose/` is created.

### 5.2 Dev mode writes rendered output to the repo tree (gitignored)

**Check:** After `cove up` in dev mode:
- `compose/.env` exists (gitignored, not tracked)
- `compose/nginx/default.conf` exists (gitignored, not tracked)
- `compose/dnsmasq/cove.conf` exists (gitignored, not tracked)
- `git status` shows these as untracked or ignored (NOT as modified)

### 5.3 Dev mode does NOT touch `~/.config/cove/`

**Check:** Before and after `cove up` in dev mode, `~/.config/cove/` is unchanged. Specifically, no `compose/` is created there.

## 6. Resolution

### 6.1 `COVE_COMPOSE_DIR` env var overrides everything

**Check:** `COVE_COMPOSE_DIR=/tmp/test cove up` uses `/tmp/test` as the compose directory.

### 6.2 CWD with `compose/inventory.yml` wins over `~/.config/cove/`

**Check:** Create a `/tmp/fake/cove/inventory.yml`. `cd /tmp/fake && cove up` uses `/tmp/fake/cove`. `~/.config/cove/compose/` is ignored (even if it exists).

### 6.3 Worktree detection still works

**Check:** From `~/Documents/code/cove/.worktrees/feature-x/`, `cove up` uses `.worktrees/feature-x/compose/` (not the main repo's compose/).

### 6.4 Git-root fallback works

**Check:** From a subdirectory of the cove repo (e.g., `~/Documents/code/cove/docs/`), `cove up` uses the repo's `compose/` (via git root detection).

### 6.5 No compose dir at all produces a clear error

**Check:** With no `compose/inventory.yml` anywhere and no `~/.config/cove/compose/`, `cove up` errors with "Run `cove init` first" or similar.

## 7. Templates

### 7.1 PII-free defaults in `group_vars/all.yml`

**Check:** `grep -E "username|email|tailscale|hostname" compose/group_vars/all.yml` returns only template variables or empty defaults.

**Specifically:**
- `admin_username: ""` (or removed entirely; the user supplies it in host_vars)
- `admin_email: ""`
- `ts_dns_name: "localhost"` (default, overridden in host_vars)

### 7.2 Rendered output contains no PII from defaults

**Check:** With default `group_vars/all.yml` and no host_vars, the rendered `compose/.env` contains no PII (no username, no Tailscale FQDN, no email).

### 7.3 Rendered output contains the user's PII when host_vars is set

**Check:** With a `host_vars/<hostname>.yml` containing `admin_username: alice`, the rendered `compose/.env` contains `FORGEJO_UID` etc. derived from `alice` (or set explicitly).

## 8. User state overlay

### 8.1 `host_vars/<hostname>.yml` values override `group_vars/all.yml`

**Check:** Set `admin_username: alice` in `~/.config/cove/state/hosts/<hostname>.yml`. Run `cove up`. The rendered config contains `alice`, not the default.

### 8.2 First-run auto-detection creates the host_vars file

**Check:** With no `~/.config/cove/state/hosts/<hostname>.yml`, run `cove up`. The file is created with auto-detected values (`admin_username` from `$USER`, etc.).

### 8.3 Missing values in host_vars are prompted

**Check:** For values that can't be auto-detected, `cove up` prompts the user (or errors clearly if non-interactive).

## 9. Upgrade

### 9.1 Version mismatch triggers re-extraction

**Setup:** `cove up` with version 0.1.0 installed. `~/.config/cove/compose/.version` says "0.1.0".

**Check:** `uv tool install .` to install 0.2.0. Run `cove up`. Stdout includes "Re-extracting resources (0.1.0 → 0.2.0)...". `~/.config/cove/compose/.version` now says "0.2.0".

### 9.2 Re-extraction preserves user state

**Check:** Before re-extraction, create a file in `~/.config/cove/state/`. After re-extraction, the file is still there.

### 9.3 Re-extraction preserves user data

**Check:** Before re-extraction, create a file in `~/Documents/cove-data/forgejo/gitea/`. After re-extraction, the file is still there.

### 9.4 Re-extraction does not preserve the old `compose/.env`

**Check:** Modify `~/.config/cove/compose/.env` (e.g., change FORGEJO_PORT). Run `cove up` with a new version. The `.env` is regenerated from defaults + host_vars, losing the manual change.

(Trade-off accepted; see musing 3.)

## 10. Teardown

### 10.1 `cove down` stops containers, preserves data

**Check:** `cove down` exits 0. `docker ps` shows no cove containers. `~/Documents/cove-data/forgejo/gitea/` is unchanged.

### 10.2 `cove down --volumes` removes Docker volumes

**Check:** `cove down --volumes` exits 0. Named volumes are removed. `~/Documents/cove-data/` is unchanged (data is bind-mounted, not in a volume).

### 10.3 `cove uninstall` removes cove state

**Check:** `cove uninstall --yes` removes:
- `~/.cache/cove/`
- macOS keychain entries (`cove/vault/root-token`, `cove/vault/unseal-{1..5}`)
- AGENTS.md guidance
- `~/.config/cove/compose/` (NEW: the extracted resources)
- `~/.config/cove/state/hosts/` (NEW: user host_vars)
- `~/.config/cove/state/logs/` (NEW: ansible logs)

But preserves:
- `~/Documents/cove-data/` (data)
- `/etc/hosts` (system)
- pf NAT rule (system)

### 10.4 `cove uninstall --purge-config` also removes `~/.config/cove/`

**Check:** `cove uninstall --yes --purge-config` removes `~/.config/cove/` entirely. `~/Documents/cove-data/` is still there.

### 10.5 `uv tool uninstall cove-cli` doesn't touch state

**Check:** `uv tool uninstall cove-cli` removes the binary. `~/.config/cove/` is unchanged. `~/Documents/cove-data/` is unchanged. Re-installing with `uv tool install cove-cli` and running `cove up` resumes.

## 11. Tests

### 11.1 Existing tests still pass

**Check:** `uv run --directory cli pytest cli/tests/` exits 0. (Currently 66 tests pass.)

### 11.2 New tests for the resolver

**Check:** Tests in `cli/tests/test_compose_resolver.py` cover:
- Resolution priority (env var > CWD > worktree > git root > ~/.config > error)
- CWD with compose/inventory.yml
- CWD without compose/ but git root has it
- Neither — error
- COVE_COMPOSE_DIR override

### 11.3 New tests for the extraction

**Check:** Tests in `cli/tests/test_extraction.py` cover:
- Extract a Traversable tree to disk
- Don't overwrite existing files (unless force)
- Idempotent
- Preserves a sibling `state/` directory

### 11.4 New tests for the version comparison

**Check:** Tests in `cli/tests/test_version.py` cover:
- Version matches → no-op
- Version mismatch → re-extract
- Missing version file → re-extract

### 11.5 New tests for first-run host_vars creation

**Check:** Tests in `cli/tests/test_host_vars.py` cover:
- Create from auto-detected values
- Prompt for missing values (or skip if non-interactive)
- Don't overwrite existing file

### 11.6 New tests for the sync-resources script

**Check:** Tests in `cli/tests/test_sync_resources.py` cover:
- `make sync-resources` (or the equivalent) produces a tree matching `compose/`
- Excludes rendered files
- Excludes `.env`

## 12. Failure modes

For each of these, the error message is checked for clarity and the exit code is non-zero.

### 12.1 Ansible not installed

```
$ cove up
Error: ansible-playbook not found on PATH. Install with: brew install ansible
```

### 12.2 Docker not running and not auto-startable

```
$ cove up
Error: Docker is not running. Start Colima with: colima start
```

### 12.3 mkcert not installed

```
$ cove up
Error: mkcert not found. Install with: brew install mkcert && mkcert -install
```

### 12.4 sudo password not provided (and sudo required)

```
$ cove up
SUDO password:
[user enters wrong password]
Error: sudo authentication failed
```

(Or whatever Ansible's error looks like — we just need to surface it clearly.)

### 12.5 `cove init` already at current version, `--force` not passed

```
$ cove init
Already initialized at version 0.1.0. Use --force to re-extract.
```

### 12.6 No compose dir, no `~/.config/cove/`

```
$ cove up
Error: No compose directory found. Run `cove init` first to extract resources.
```

### 12.7 Port 8443 already in use

```
$ cove up
Error: Port 8443 is already in use. Stop the conflicting process or change nginx_https_port in
~/.config/cove/state/hosts/<hostname>.yml.
```

### 12.8 Tailscale is configured but `tailscale status` fails

```
$ cove up
Error: Tailscale is configured (TAILSCALE_FQDN set) but `tailscale status` failed.
Either fix Tailscale or unset TAILSCALE_FQDN.
```

### 12.9 1Password not signed in

```
$ cove up
Pulling credentials from 1Password...
Error: 1Password CLI not signed in. Run: op signin
```

### 12.10 Forgejo container fails to start

```
$ cove up
...
TASK [Bring up pod via docker compose] *****
fatal: FAILED! => {"changed": false, "msg": "..."}
Error: docker compose failed. Check `docker compose -f ~/.config/cove/compose/docker-compose.yml ps`.
```

## What I'm NOT testing in this migration

- **Performance** — `cove up` takes the same time it does today. No perf testing.
- **Load testing** — Forgejo/Vault at scale is out of scope.
- **Cross-platform** — macOS only. Linux/Windows support is future work.
- **Multiple hosts** — single host only. Multi-host (e.g., dev + prod) is future work.
- **Schema migration of data** — if Forgejo 14 → 15 needs data migration, that's a separate concern.

## Test infrastructure needs

- **pytest fixtures** for `tmp_path` (use a clean `~/.config/cove/` per test)
- **Mocking** for `subprocess.run` (don't actually call ansible/docker during unit tests)
- **Mocking** for `tailscale status`, `mkcert`, `colima` (so tests don't require them)
- **Integration tests** that DO call real tools — gated behind a marker, run manually or in CI on a real Mac

This is the criteria. Next musing: the migration plan — phases, ordering, what to do first.
