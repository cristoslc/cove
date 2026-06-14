# Musing 3 — Mechanism Design

OK, the journeys are clear. Now the mechanism. This is the design musing. I'm going to commit to a design, defend it against the obvious alternatives, and call out the gotchas.

## The shipping model: bundle the whole `compose/` tree as a Python package resource

The cleanest answer is: bundle the entire `compose/` directory as a Python package resource. Why the whole tree? Because it has internal relative paths. `docker-compose.yml` references `./nginx/`, `./dnsmasq/`, `./vault/vault.hcl`. The Ansible playbooks reference `roles/`, `group_vars/`, `host_vars/`, `inventory.yml` via `playbook_dir`. These are not separable.

```
cli/cove/resources/compose/
├── .env.example                          # template, no machine values
├── docker-compose.yml                    # uses ${VAR:-default} extensively
├── inventory.yml                         # just localhost
├── bringup.yml                           # playbook
├── bootstrap_vault.yml                   # playbook
├── provision_vault_user.yml              # playbook
├── provision_forgejo.yml                 # playbook
├── provision_pages.yml                   # playbook
├── group_vars/
│   └── all.yml                           # defaults, must be PII-free
├── host_vars/
│   └── localhost.yml.example             # per-host override template
├── roles/
│   └── os_keystore/                      # macOS keychain role
├── nginx/
│   └── default.conf.j2                   # template
├── dnsmasq/
│   ├── Dockerfile                        # image build
│   └── cove.conf.j2                      # template
├── vault/
│   └── vault.hcl                         # static
├── files/
│   ├── cove-sudoers.j2                   # template (was cove-sudoers, PII in it)
│   └── actions/
│       ├── configure-pages/action.yml
│       ├── deploy-pages/action.yml
│       └── upload-pages-artifact/action.yml
└── seeds/
    └── vault-user.yaml
```

The package manifest picks it up:

```toml
[tool.setuptools.package-data]
"cove.resources" = ["**/*"]
"cove.templates" = ["*.j2"]  # AGENTS.md templates stay
```

`cove` exposes it via `importlib.resources`:

```python
from importlib.resources import files

resource_root = files("cove.resources.compose")
# resource_root is a Traversable, supports joinpath, read_text, is_dir, iterdir
```

## The two-mode resolution algorithm

The CLI needs to pick a "compose directory" for any operation. Here's the algorithm:

```python
def resolve_compose_dir() -> Path:
    """Return the compose directory to use for this invocation.

    Priority:
    1. $COVE_COMPOSE_DIR env var (escape hatch for tests / power users)
    2. CWD or .worktrees/<cwd.name>/ if compose/inventory.yml is there (dev mode)
    3. Git root's compose/ if it has inventory.yml (dev mode, running from a subdir)
    4. ~/.config/cove/compose/ if it exists (installed mode, after cove init)
    5. Otherwise: raise with a clear "run cove init" message
    """
```

Cases:

| Condition | Mode | Path used |
|-----------|------|-----------|
| `COVE_COMPOSE_DIR=/foo` | override | /foo |
| CWD is repo root, has `compose/inventory.yml` | dev | `<cwd>/compose` |
| CWD is repo worktree, has `compose/inventory.yml` | dev | `<cwd>/compose` |
| Git root has `compose/inventory.yml` | dev | `<git_root>/compose` |
| `~/.config/cove/compose/inventory.yml` exists | installed | `~/.config/cove/compose` |
| None of the above | error | "Run `cove init` first" |

The current `_find_compose_dir()` is too narrow. It only handles dev mode. The new resolver is symmetric: dev and installed both work.

## Extraction: how `cove init` works

```python
def init(force: bool = False) -> None:
    config_dir = Path.home() / ".config" / "cove"
    compose_dir = config_dir / "compose"
    state_dir = config_dir / "state"
    version_file = compose_dir / ".version"

    current_version = cove_version()  # from cove.__version__

    if compose_dir.exists():
        if not force:
            existing = version_file.read_text().strip() if version_file.exists() else "unknown"
            if existing == current_version:
                click.echo(f"Already initialized at version {current_version}.")
                return
            click.echo(f"Existing compose/ at version {existing}, current is {current_version}.")
            if not click.confirm("Re-extract resources? Your data in ~/Documents/cove-data/ is preserved."):
                return

    config_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)

    resource_root = files("cove.resources.compose")
    _extract_tree(resource_root, compose_dir)
    version_file.write_text(current_version + "\n")

    _ensure_ansible_collection("community.docker")

    click.echo(f"Initialized cove at {compose_dir} (version {current_version}).")
    click.echo("Next: cove up")
```

`init` is **idempotent and safe to re-run**. It preserves user data. It only overwrites the shipped resource tree.

The `_extract_tree` is a recursive copy from `importlib.resources` to disk. It's the only non-trivial utility.

## Where rendered output lives

This is the "surprise write" question from musing 1. Where does `compose/.env`, `compose/nginx/default.conf`, `compose/dnsmasq/cove.conf` go?

**Decision:** in installed mode, all rendered output goes to `~/.config/cove/state/rendered/`:

```
~/.config/cove/
├── compose/                              # shipped resources, read-only at runtime
│   ├── .version                          # marks which cove-cli version extracted this
│   ├── bringup.yml
│   ├── docker-compose.yml
│   └── ...
└── state/
    ├── rendered/                         # output of template renders
    │   ├── compose.env                   # rendered .env (was compose/.env)
    │   ├── nginx/default.conf            # rendered nginx config
    │   └── dnsmasq/cove.conf             # rendered dnsmasq config
    ├── hosts/<hostname>.yml              # Ansible host_vars, per machine
    └── logs/                             # ansible-playbook logs if --log
```

The `docker-compose.yml` is updated to read from these rendered paths via the `.env` file location (Docker Compose reads `.env` from the project directory, but we can use a different env file: `docker compose --env-file <path>`). And the bind-mount paths in `docker-compose.yml` need to be absolute or use the new state dir.

Wait, this is where it gets fiddly. Let me think more carefully.

**The current `docker-compose.yml` does this:**

```yaml
volumes:
  - ${FORGEJO_DATA_ROOT}/forgejo/gitea:/data/gitea
  - ${NGINX_CONF_DIR:-./nginx}/default.conf:/etc/nginx/conf.d/default.conf:ro
  - ${COVE_DATA_ROOT}/certs:/certs:ro
```

The `${COVE_DATA_ROOT}` and `${NGINX_CONF_DIR}` come from `compose/.env`. In installed mode, we want:
- `${COVE_DATA_ROOT}` → `~/Documents/cove-data` (still works)
- `${NGINX_CONF_DIR}` → the rendered nginx config dir, which is `~/.config/cove/state/rendered/nginx`

Hmm. The nginx config isn't shipped (it's rendered from the template). So the path needs to point at the rendered dir.

Two ways to do this:

**Way A: Render nginx.conf into the shipped compose tree (where the source template is)**

The Ansible template task writes to `<compose_dir>/nginx/default.conf` (where it lives today). In installed mode, this is `~/.config/cove/compose/nginx/default.conf`. The `compose/` tree becomes both shipped-source AND rendered-output.

Pro: no `docker-compose.yml` changes. Just keep rendering into the shipped tree.
Con: the shipped tree is no longer immutable — Ansible writes to it. But: the writes are deterministic and idempotent, and we can `cove init --force` to nuke and re-extract.

**Way B: Render to a separate state dir, point `docker-compose.yml` at it**

Render to `~/.config/cove/state/rendered/nginx/default.conf`. The `docker-compose.yml` references this path.

Pro: clean separation. Shipped tree is immutable.
Con: the `docker-compose.yml` needs a different env var pointing at the state dir, AND the env var needs to be in the `.env` file in the project directory. So either the `.env` is also rendered into the project dir, or the env var is hardcoded to a derived path.

**Way A is simpler and works.** The only catch is that "the shipped tree is read-only" isn't literally true. But it IS logically read-only — re-running `cove init --force` produces the same tree (modulo the rendered files, which are deterministic from the templates and the group_vars).

**Decision: Way A. Rendered output goes into the compose tree (which is on disk, not in the package). In installed mode, the compose tree is `~/.config/cove/compose/` — owned by cove, but writable. In dev mode, the compose tree is the repo's `compose/` — but the CLI should refuse to write rendered output there (it would pollute the repo).**

Wait, that's a contradiction. Let me re-think.

Actually, in **dev mode**, Alex WANTS the rendered output in the repo (so they can inspect it, debug it, etc.). The "the repo is publishable" concern is about TRACKED files, not about the working tree. `compose/nginx/default.conf` can be in the working tree as long as it's gitignored. And `git status` shows it as an untracked file (or `--ignored` for a fully-ignored one).

**Refined decision:**
- In **dev mode**: rendered output goes into the repo tree (where the templates live), at `compose/.env`, `compose/nginx/default.conf`, etc. These are gitignored.
- In **installed mode**: rendered output also goes into the compose tree, but the tree is `~/.config/cove/compose/` (not the repo). The repo is never touched.

This is consistent with today, except `~/.config/cove/compose/` is a new location.

So the only difference from today is: instead of "compose dir is found in the repo checkout", the compose dir is found at `~/.config/cove/compose/` (in installed mode) or the repo checkout (in dev mode). Ansible runs in either location, and renders go into that tree.

**The `.env` file question:** Ansible's `bringup.yml` writes `compose/.env`. In dev mode this is the repo. In installed mode this is `~/.config/cove/compose/.env`. Same playbook, different output location. ✓

**The user-state overlay question:** what about user customizations? Today, Alex can edit `compose/group_vars/all.yml` in the repo to change a default. In installed mode, where do they edit?

Option: `~/.config/cove/state/hosts/<hostname>.yml` (Ansible host_vars). Ansible's `host_vars/<hostname>.yml` overrides `group_vars/all.yml`. The user adds their machine-specific values here. The shipped `group_vars/all.yml` is never touched.

For dev mode, the user can edit `compose/group_vars/all.yml` directly (it's in their repo). But the cleaner pattern is: dev mode also uses `host_vars/<hostname>.yml` from the user state dir, layered over the repo's `group_vars/all.yml`.

Wait, Ansible only loads host_vars from the inventory host's directory. If the user has `~/.config/cove/state/hosts/MBPBK-202602.yml`, Ansible won't find it unless the inventory says so.

**Mechanism:** The CLI sets `ANSIBLE_HOSTS` or uses `--extra-vars` to inject the user state dir. Or, more cleanly: the CLI maintains a `~/.config/cove/state/inventory.yml` that references both the shipped and the user state dir.

Actually, the cleanest mechanism: when running Ansible, the CLI passes:

```
ansible-playbook -i <compose_dir>/inventory.yml \
  -e "@<state_dir>/hosts/<hostname>.yml" \
  -e compose_dir=<compose_dir> \
  -e state_dir=<state_dir> \
  <playbook>
```

`@file` is Ansible's syntax for "load variables from this YAML file". The user state file overrides the playbook's default vars.

**User state file content:**

```yaml
# ~/.config/cove/state/hosts/MBPBK-202602.yml
admin_username: cristos
admin_email: lc.cristos@gmail.com
op_vault: Private
ts_dns_name: mbpbk-202602.taila90e7.ts.net  # auto-detected at runtime
```

This is the file that has PII. It is OUTSIDE the repo. It is not tracked. It is created on first run with auto-detected values + a prompt for anything that can't be auto-detected.

**Auto-detection candidates:**

| Var | How to detect |
|-----|---------------|
| `admin_username` | `$USER` env var |
| `admin_email` | git config user.email, fallback to prompt |
| `op_vault` | env var `OP_VAULT`, fallback to "Private" |
| `ts_dns_name` | `tailscale status --json`, fallback to "localhost" |
| `cove_data_root` | `$HOME/Documents/cove-data` (constant for now) |

**First-run detection:** `cove up` checks if `~/.config/cove/state/hosts/<hostname>.yml` exists. If not, creates it with auto-detected values, then proceeds. If a value can't be auto-detected, prompts the user.

## The "what gets bundled" decision tree

I keep going back and forth. Let me lock this down:

| File | Bundled? | Why |
|------|----------|-----|
| `docker-compose.yml` | YES | Core, machine-independent except for env vars |
| `.env.example` | YES | Template, no machine values |
| `inventory.yml` | YES | Just localhost |
| `bringup.yml` | YES | Playbook |
| `bootstrap_vault.yml` | YES | Playbook |
| `provision_vault_user.yml` | YES | Playbook |
| `provision_forgejo.yml` | YES | Playbook |
| `provision_pages.yml` | YES | Playbook |
| `group_vars/all.yml` | YES | Defaults, PII-stripped |
| `host_vars/localhost.yml.example` | YES | Template, no PII |
| `roles/os_keystore/` | YES | Ansible role |
| `nginx/default.conf.j2` | YES | Template |
| `dnsmasq/Dockerfile` | YES | Image build |
| `dnsmasq/cove.conf.j2` | YES | Template |
| `vault/vault.hcl` | YES | Static config |
| `files/cove-sudoers.j2` | YES | Template (was PII) |
| `files/actions/**` | YES | Action definitions |
| `seeds/vault-user.yaml` | YES | Vault policy |

What does NOT get bundled:
- The user's state files (`~/.config/cove/state/`)
- The user's data (`~/Documents/cove-data/`)
- The host_vars/ per-host overrides
- The rendered `.env`, `nginx/default.conf`, `dnsmasq/cove.conf` (these are derived, re-rendered on each `cove up`)

## The version-comparison re-extraction

The `~/.config/cove/compose/.version` file tracks the cove-cli version that produced this extraction. On every `cove up`, the CLI:

1. Reads its own `__version__` (from the installed package)
2. Reads `~/.config/cove/compose/.version`
3. If they differ, prompts the user OR re-extracts automatically (configurable)

Auto-re-extract is the default. The user sees: "Detected version mismatch: 0.1.0 → 0.2.0, re-extracting resources..." and it happens.

What if the new version has a breaking change in the `docker-compose.yml`? The re-extraction is a copy operation. The new tree replaces the old. The user's data is untouched. The user's host_vars is untouched (it's in a different dir).

**Gotcha:** what if the new version renames an env var? The old `compose/.env` is overwritten with the new template. The user's previous values are lost. The user gets a fresh `.env` with defaults.

**Mitigation:** before overwriting, the CLI could back up the old `.env` to `~/.config/cove/state/rendered/compose.env.bak.<old-version>`. Or, smarter: render the new `.env` by overlaying the old values onto the new template (Jinja2 with `{% set _ = ... %}` or a simple key-by-key merge). This is more work but it's the right thing.

**Decision: simple overwrite for now.** The user can re-enter values manually if needed. Add backup-and-restore as a future enhancement.

## Path resolution within Ansible

Ansible's `playbook_dir` is the directory containing the playbook. In the new world, the playbook is at `~/.config/cove/compose/bringup.yml`, so `playbook_dir` is `~/.config/cove/compose/`. The references to `roles/`, `group_vars/`, `inventory.yml` all work relative to `playbook_dir`. ✓

The `nginx_conf_dir` and `dnsmasq_conf_dir` vars default to `{{ playbook_dir }}/nginx` and `{{ playbook_dir }}/dnsmasq` (in `group_vars/all.yml`). So the rendered nginx config goes to `<playbook_dir>/nginx/default.conf` — in installed mode, `~/.config/cove/compose/nginx/default.conf`. ✓

The `docker-compose.yml` references `./nginx/default.conf` (line 57). In installed mode, that's `~/.config/cove/compose/nginx/default.conf`. ✓

Everything resolves naturally as long as Ansible is invoked from inside the compose tree. The CLI does `cwd=compose_dir` before running the playbook.

## Ansible collections: a host prereq

`cove init` runs `ansible-galaxy collection install community.docker` (and any other required collections). The `requirements.yml` file in `compose/` lists them. The CLI runs `ansible-galaxy collection install -r <compose_dir>/requirements.yml`.

This is idempotent. If already installed, no-op.

If `ansible-galaxy` isn't on PATH (Ansible not installed), `cove init` errors: "Ansible is required. Install: `brew install ansible`".

## The big question I keep avoiding: do we keep `compose/` in the repo?

**Pro keeping:**
- Dev mode uses it directly
- The repository is the canonical source of the resources (for `cove init --force` to work, we need a source of truth)
- It's already there
- Deleting it would be a big commit and would break `git diff` for in-flight changes

**Con keeping:**
- It's redundant with the package resource
- Two sources of truth → they could drift

**Compromise:** keep `compose/` in the repo, and the package resource is a duplicate of the repo's `compose/`. The repo is the SOURCE for the package resource. A build step copies `compose/` to `cli/cove/resources/compose/` and the package ships the copy.

This adds a "drift risk" — someone edits `compose/` but doesn't rebuild the package. We mitigate by:
- A test that runs `cove init --force` from a fresh `~/.config/cove/` and diffs against the repo
- Or a build script that's part of `pyproject.toml` and is run as part of `uv build`

Actually the cleanest solution: **at runtime, the CLI uses the package resource (immutable). For dev mode, the CLI uses the repo's `compose/` (mutable, fast iteration). For release, the developer runs `make sync-resources` (or similar) to copy `compose/` into `cli/cove/resources/compose/`.**

This is the right answer. The cost is one extra build step. The benefit is no drift (because there's a sync step that can be tested).

**Alternative: symlink the package resource to the repo during dev.** No — this breaks `uv tool install` because the symlink would point into the repo.

**Alternative: detect the source tree at build time.** The CLI's `cove init` checks if it's running from a development install (e.g., `pip show cove-cli` shows the path is inside the repo) and uses the repo's `compose/` if so. Otherwise uses the package resource.

**Decision: keep the sync step.** A `make sync-resources` or `cli/scripts/sync_compose_resources.py` that copies `compose/` → `cli/cove/resources/compose/`. Run it as part of `uv build` or as a pre-commit check. The package resource is the shipped truth; the repo is the dev source.

## The `compose/` → `cli/cove/resources/compose/` migration

This is a one-time copy. Steps:

1. Create `cli/cove/resources/compose/` directory
2. Copy entire `compose/` tree (minus `.env`, `__pycache__/`, rendered files)
3. Edit `pyproject.toml` to add the package-data entry
4. Add a `.gitignore` in `cli/cove/resources/compose/` to exclude rendered files (defense in depth)
5. The repo's `compose/` stays for dev mode

Files NOT to copy (because they're rendered, not source):
- `compose/.env` (rendered)
- `compose/nginx/default.conf` (rendered)
- `compose/dnsmasq/cove.conf` (rendered)

Files in `compose/` that are gitignored today:
- I'll check `.gitignore` to see what's already there

(Checking... let me look.)

OK I read `.gitignore` already:
- `__pycache__/`
- `*.pyc`
- `bin/`
- `compose/.env`
- `compose/.env.local`
- `compose/nginx/default.conf`
- `compose/dnsmasq/cove.conf`
- `cove-data/` (probably)
- `.worktrees/`
- Various test artifacts

So the rendered files are already gitignored. The repo's `compose/` doesn't have them tracked. Good. I just need to make sure `cli/cove/resources/compose/` doesn't track them either (add the same gitignore to the resources subdir).

## The "what is `cove init` vs `cove up`" decision

Two options:

**Option 1: Separate commands**
- `cove init` — extract resources, set up user state
- `cove up` — assume init has been run, error if not

**Option 2: `cove up` is self-bootstrapping**
- `cove up` checks if init has been run, runs it if not, then proceeds

**Option 3: `cove up` is self-bootstrapping but `cove init` exists for explicit use**

Going with **Option 3**:
- `cove init` exists, is idempotent, is the "set up once" command
- `cove up` auto-inits if needed
- `cove init --force` re-extracts resources (e.g., after `uv tool upgrade`)
- `cove init --purge` removes `~/.config/cove/compose/` (preserves user state)

## Summary of the mechanism

1. **Ship the whole `compose/` tree as a package resource** at `cli/cove/resources/compose/`. Sync from `compose/` to the resources dir as a build step.
2. **Extract on first run** to `~/.config/cove/compose/`. Track version in `.version` file.
3. **Re-extract on version mismatch** automatically.
4. **User state lives at `~/.config/cove/state/`**:
   - `hosts/<hostname>.yml` — Ansible host_vars override
   - `rendered/` — output of template renders (if we choose Way B; we're using Way A so this is empty)
   - `logs/` — ansible logs if `--log` passed
5. **Dev mode uses the repo's `compose/`** directly. No extraction, no `~/.config/cove/compose/`.
6. **Ansible invocations** are wrapped by the CLI which passes:
   - `-i <compose_dir>/inventory.yml`
   - `-e compose_dir=<compose_dir>`
   - `-e state_dir=<state_dir>`
   - `-e @<state_dir>/hosts/<hostname>.yml` (user overrides)
7. **First-run detection** for `~/.config/cove/state/hosts/<hostname>.yml`: create with auto-detected values, prompt for the rest.
8. **Ansible collections** are installed by `cove init` from `requirements.yml`.
9. **The CLI is the orchestrator** — the user never runs `ansible-playbook` directly.

OK that's the mechanism. Next: acceptance criteria — what does "it works" mean exactly.
