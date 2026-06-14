# Musing 1 — State of the World

What does "stateless config" actually mean for cove? Before I can answer that, I need to be honest about where config lives today and all the places it's touched. No solution design yet — just inventory.

## The honest inventory of "where does config live today"

### Layer 1: The repo (source of truth in dev mode)

```
/Users/cristos/Documents/code/cove/
├── compose/                              ← THE config
│   ├── .env                              ← rendered, machine-specific, gitignored
│   ├── .env.example                      ← template
│   ├── bringup.yml                       ← Ansible playbook #1
│   ├── bootstrap_vault.yml               ← Ansible playbook #2
│   ├── provision_vault_user.yml          ← Ansible playbook #3
│   ├── provision_forgejo.yml             ← Ansible playbook #4
│   ├── provision_pages.yml               ← Ansible playbook #5
│   ├── inventory.yml                     ← Ansible inventory (just localhost)
│   ├── group_vars/
│   │   └── all.yml                       ← all default variables, includes PII
│   ├── host_vars/
│   │   └── MBPBK-202602.yml              ← machine-specific host vars
│   ├── roles/
│   │   └── os_keystore/                  ← Ansible role
│   ├── nginx/
│   │   ├── default.conf.j2               ← nginx config template
│   │   └── default.conf                  ← rendered nginx config (in tree but gitignored)
│   ├── dnsmasq/
│   │   ├── Dockerfile                    ← dnsmasq image build
│   │   ├── cove.conf.j2                  ← dnsmasq config template
│   │   └── cove.conf                     ← rendered dnsmasq config
│   ├── vault/
│   │   └── vault.hcl                     ← static vault config
│   ├── files/
│   │   ├── cove-sudoers                  ← sudoers file with username (PII)
│   │   └── actions/                      ← 3 GitHub Actions
│   └── seeds/
│       └── vault-user.yaml               ← Vault user policy
├── cli/cove/                             ← the CLI source
│   ├── cli.py                            ← finds compose/ via _find_compose_dir()
│   ├── project.py                        ← injects AGENTS.md guidance
│   ├── creds.py                          ← credential subcommands
│   ├── vault_cache.py                    ← Vault client
│   ├── vault_unseal.py                   ← Vault keychain integration
│   ├── local_cache.py                    ← local 1Password cache
│   ├── op_bulk_write.py                  ← 1Password bulk writer
│   └── templates/                        ← Jinja2 templates for AGENTS.md
│       ├── detail-cove.md.j2
│       ├── fj-reference.md.j2
│       └── project-guidance.md.j2
├── pyproject.toml                        ← name = "cove-cli", deps: click, jinja2, pyyaml, requests
├── seeds/                                ← separate from compose/seeds/
│   └── forgejo-creds.yaml                ← SSH key path with hostname (PII)
├── docs/                                 ← docs (purposely out of scope for THIS musing)
└── AGENTS.md                             ← guidance for agents
```

### Layer 2: The installed package (current state — package is incomplete)

`uv tool install cove-cli` produces:
- A `cove` binary in `~/.local/bin/` (or wherever uv puts it)
- The `cove_cli` package installed under `~/.local/share/uv/tools/cove-cli/`
- The `cove` Python package next to it with all the modules

What's in the package: just `cli/cove/`. The `compose/` directory is NOT bundled. The CLI tries to find it via `_find_compose_dir()` which looks at CWD and the git root. So an installed cove outside the repo checkout is broken — there is no compose/ to find.

This is the actual gap. The user said "cove needs to be installable via uv" but right now it is *not* installable in any meaningful sense — installing it gives you a CLI that errors out the moment you run it.

### Layer 3: The host (machine state)

```
~/
├── Documents/cove-data/                  ← ALL runtime data lives here
│   ├── certs/
│   │   ├── cove.local.pem                ← mkcert-generated TLS cert
│   │   └── cove.local-key.pem            ← TLS private key
│   ├── forgejo/
│   │   ├── gitea/                        ← Forgejo SQLite + repos
│   │   ├── git/                          ← bare git repos
│   │   └── ssh/                          ← Forgejo SSH host keys
│   ├── vault/
│   │   ├── data/                         ← Vault Raft storage
│   │   └── logs/                         ← Vault audit logs
│   ├── pages/sites/                      ← Pages static content
│   ├── nginx/                            ← (empty, nginx reads from compose/nginx/)
│   ├── dnsmasq/
│   │   └── cove.conf                     ← rendered dnsmasq config (copied from compose/)
│   └── .env (no, this is in compose/)     ← actually no, .env is in compose/
├── Library/Keychains/                    ← macOS keychain (Vault unseal keys, root token)
└── .cache/cove/                          ← 1Password credential cache (removed by uninstall)
```

### Layer 4: System state (host-level)

```
/etc/hosts                               ← 127.0.0.1 cove git.cove vault.cove hc.cove
/etc/sudoers.d/cove                      ← passwordless sudo for ansible (PII: username)
/etc/pf.conf or pfctl                    ← NAT 443→8443 rule
~/.docker/contexts/meta/                 ← docker context use colima
~/Library/Application Support/Colima/    ← the actual VM
```

## What "stateless" actually means

I keep using the word "stateless" but I need to pin it down. Here are the things I could mean:

### Definition A: No machine-specific content in tracked files

The repo contains only:
- Templates (`.j2` files)
- Code (Python, Ansible playbooks)
- Static assets (Dockerfile, vault.hcl)
- Example/default values that are clearly NOT a specific machine

Any "I am machine X" values are in `~/.config/cove/` or derived at runtime.

This is what the user is gesturing at. The repo is publishable to GitHub without scrubbing. `git grep` of the username returns zero hits. The Tailscale FQDN is gone from the default.

### Definition B: `cove up` works without the repo

After `uv tool install cove-cli`, running `cove up` from any directory on any host:
- Creates a working cove (forge, vault, ingress)
- Uses paths under `~/.config/cove/`
- Doesn't require `git clone` first

This is what "installable" means. The CLI carries the config inside it.

### Definition C: `cove` is genuinely stateless (no data on disk)

This is the Kubernetes interpretation. The container is immutable; all state is in the database. This is NOT what we want — cove is BY DESIGN a stateful system. The data dir, the keychain, the TLS certs are all necessary state. The "state" we want to externalize is the *configuration*, not the *data*.

### Definition D: Idempotent `cove up`

`cove up` can be run repeatedly. If everything is already up, it's a no-op. If something is down, it brings it up. Idempotency is related to statelessness but not the same.

**I'm going with A + B:** the repo has no machine-specific content, and `cove up` works without the repo. Idempotency (D) is a separate concern that's already mostly there.

## The "where does the boundary sit" question

Once the repo is clean, the question becomes: where does the boundary between "shipped config" and "user data" sit?

```
SHIPPED (in the uv tool install)     USER-WRITTEN (in ~/.config/cove)
├── docker-compose.yml                ├── .env (rendered, with machine values)
├── inventory.yml                     ├── .env.example is shipped, copied to .env on init
├── group_vars/all.yml                ├── host_vars/<hostname>.yml (NEW)
├── bringup.yml                       │
├── bootstrap_vault.yml               │   ← user can override group_vars/ at this layer
├── provision_*.yml                   │
├── roles/os_keystore/                │
├── nginx/default.conf.j2             │
├── dnsmasq/Dockerfile                │
├── dnsmasq/cove.conf.j2              │
├── vault/vault.hcl                   │
├── files/actions/                    │
├── seeds/vault-user.yaml             │
└── .env.example                      │
```

User-written is what the user customizes for their machine. This includes:
- The actual `host_vars/<hostname>.yml` for the specific machine
- The rendered `.env` (or its equivalents)
- A `cove.toml` or similar for user preferences

The shipped file is a *tree*, the user file is a *tree*, and the merge is "load all from shipped, then layer user over it". The simplest version is: shipped is the source of truth, user files only contain overrides.

## Touch points — every place config is read or written

This is what I need to enumerate to understand the scope of "stateless migration":

### Read paths (config → system)

1. **CLI → compose/**: `_find_compose_dir()` walks up from CWD looking for `inventory.yml`. Used by `cove up`, `cove down`, `cove uninstall`.
2. **CLI → templates/**: `files("cove.templates")` in `project.py` reads Jinja2 templates from the installed package. Used by `cove install`.
3. **CLI → cli.py hardcoded paths**: `_find_compose_dir()` checks `.worktrees/{cwd.name}/compose/` for in-progress work.
4. **Ansible → compose/**: All 5 playbooks live in compose/ and use `playbook_dir` to reference siblings (group_vars/, host_vars/, roles/, nginx/, dnsmasq/).
5. **Ansible → ~/.cache/cove/**: The 1Password cache for credentials. Removed by uninstall.
6. **Ansible → ~/Library/Keychains/**: Vault unseal keys via `security` command (macOS).
7. **docker-compose → compose/**: `./nginx/default.conf`, `./dnsmasq/`, `./vault/vault.hcl` are relative paths resolved from the compose file's directory.
8. **docker-compose → .env**: `${FORGEJO_*}` vars read from `compose/.env` (rendered by bringup.yml).
9. **dnsmasq → data dir**: `/etc/dnsmasq.d/cove.conf` is bind-mounted from `${COVE_DATA_ROOT}/dnsmasq/cove.conf` (rendered by bringup.yml).
10. **nginx → data dir**: TLS certs bind-mounted from `${COVE_DATA_ROOT}/certs/`.
11. **mkcert → data dir**: Certs written to `${cove_data_root}/certs/cove.local.pem`.

### Write paths (system → config)

1. **bringup.yml → compose/.env**: Renders `${COVE_DATA_ROOT}` and other env vars into `compose/.env` (mode 0600).
2. **bringup.yml → ${COVE_DATA_ROOT}/dnsmasq/cove.conf**: Renders dnsmasq template to the data dir.
3. **bringup.yml → compose/nginx/default.conf**: Renders nginx template *in the repo tree* (this is the part that pollutes the repo with machine-specific data).
4. **bringup.yml → /etc/hosts**: Adds `127.0.0.1 cove git.cove vault.cove hc.cove` (requires sudo).
5. **bringup.yml → pf NAT**: Configures `rdr pass on lo0 inet proto tcp from any to 127.0.0.1 port 443 -> 127.0.0.1 port 8443` (requires sudo).
6. **bringup.yml → ~/Library/Keychains/**: Implicitly via the macOS `security` command from the bootstrap_vault playbook.
7. **provision_forgejo.yml → Forgejo REST API**: Creates admin user, repos, etc.
8. **provision_vault_user.yml → Vault REST API**: Creates a Vault user.
9. **cove install → AGENTS.md**: Injects cove guidance into the project or global AGENTS.md.

### The "surprise" write: nginx default.conf in the repo tree

`bringup.yml` task 147-151:

```yaml
- name: Render nginx config from template
  ansible.builtin.template:
    src: "{{ nginx_conf_dir }}/default.conf.j2"
    dest: "{{ nginx_conf_dir }}/default.conf"
    mode: "0644"
```

This writes a *rendered, machine-specific* `default.conf` into `compose/nginx/` — the same directory the `nginx.conf` template lives in. This file should be ephemeral, not a tracked artifact. The reason it works today is `.gitignore` excludes `compose/nginx/default.conf` (I assume — let me verify).

Same pattern for `compose/dnsmasq/cove.conf`. Let me check the gitignore situation.

Actually the rendered nginx config goes into the repo tree only when running from the repo. When running from an extracted copy at `~/.config/cove/compose/`, it stays in the extracted tree. So this is a "where do I write" decision: write to the extracted tree, never to the shipped source.

## The two-direction problem

The current code has config flowing in two directions:
- **In:** read compose/ (relative path from CWD) to learn how to bring up the platform
- **Out:** write back into compose/ (the same tree) to record machine-specific rendered output

For "stateless" to work, the "in" and "out" must point to different trees:
- **In:** read from the immutable shipped source (extracted resource, or repo checkout in dev mode)
- **Out:** write to the mutable user state tree (`~/.config/cove/`)

The shipped source is read-only. The user state tree is read-write. The merge happens at runtime (Ansible loads `host_vars/<hostname>.yml` over `group_vars/all.yml`, etc.).

## What "PII" means in this context

Before I plan the migration I need to enumerate every tracked file that contains machine-specific values. The user mentioned username, Tailscale FQDN. From the audit:

| File | PII | Notes |
|------|-----|-------|
| `compose/group_vars/all.yml` | `admin_username: cristos` (line 34), `admin_email: lc.cristos@gmail.com` (line 35) | Default values that look like specific-machine values |
| `compose/group_vars/all.yml` | `ts_dns_name: "localhost"` (line 43) | Overridden at runtime |
| `compose/host_vars/MBPBK-202602.yml` | filename is hostname (line 1: `# This Mac`) | Per-host override file |
| `compose/files/cove-sudoers` | username in sudoers | Probably my user |
| `compose/dnsmasq/cove.conf` | rendered with `ts_dns_name` | Tailscale FQDN hardcoded |
| `compose/files/actions/*/action.yml` | `COVE_FQDN` defaults | Tailscale FQDN hardcoded |
| `seeds/forgejo-creds.yaml` | hostname + SSH key paths | Machine-specific |
| `__pycache__/...` | binary, contains username | Should be gitignored already |
| `compose/.env` | rendered machine state | Should be gitignored already |

The clean fix: defaults in `group_vars/all.yml` are PII-free (use `admin_username: ""` or `{{ admin_username | default("") }}`), per-host values go in `host_vars/<hostname>.yml` (which is gitignored).

## Conclusion (still no solution)

Three things I now know:
1. The "config" is two trees: shipped (read-only source) and user state (read-write overlay). The migration is splitting them.
2. The shipped source contains machine-specific values that need to be either templated (default = empty) or moved to host_vars.
3. The CLI currently couples shipped and user state by always pointing to the repo checkout. The migration is making the CLI point to `~/.config/cove/compose/` for installed mode and the repo checkout for dev mode, with the user state written into `~/.config/cove/state/` rather than back into the compose tree.

That's enough for musing 1. Next: workflows and journeys — the user-facing paths that touch this machinery.
