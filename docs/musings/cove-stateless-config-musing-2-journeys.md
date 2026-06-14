# Musing 2 — Config Workflow Journeys

OK so I have the inventory. Now I need to walk through the actual journeys. Not "what files exist" but "what does a person actually do, step by step, and where does the config flow touch their life."

I'm going to be a person. Let me give them a name: Alex. Alex is the operator. They have one laptop. They run macOS. They want cove to work.

## Journey 0 — Alex discovers cove

Alex reads a tweet or a blog post. They see `uv tool install cove-cli` and `cove up`. They think: "OK let me try this."

Current state: `cove up` errors out because there's no `compose/` directory. So the journey ends at step 1.

Target state: Alex has never heard of Compose or Ansible. They run the install command and `cove up` and it just works (or gives them clear error messages about what host prerequisites are missing).

**Implicit acceptance:** the user never sees "compose/", "playbook", "Ansible", "mkcert", "Colima", or "dnsmasq" in the happy-path output. These are all internal mechanisms. The only thing Alex should need to know:
- "Install Homebrew packages X, Y, Z" (one-time host setup)
- "Run `cove up`"
- "Open https://git.cove/ in your browser"

## Journey 1 — First-time install (the meat of the journey)

This is THE journey. If this doesn't work, nothing else matters.

**Pre-conditions:**
- macOS, fresh laptop
- Alex has `brew`, `uv`, and `git` installed (developer)
- Alex does NOT have Ansible, Colima, mkcert, Docker, etc.

**Steps (current state, what should happen):**

| # | Step | Current | Target |
|---|------|---------|--------|
| 1 | `uv tool install cove-cli` | installs binary, no compose/ | installs binary, no compose/ |
| 2 | `cove up` | errors: "Could not find compose/inventory.yml" | checks for prerequisites, prints install instructions |
| 3 | Alex runs `brew install ansible colima mkcert && colima start && mkcert -install` | nothing happens | Alex runs the printed install commands |
| 4 | `cove up` (again) | still errors, no compose/ | extracts resources, writes config, brings up containers |
| 5 | Alex opens https://git.cove/ | nothing | Forgejo login page |
| 6 | `cove creds vault-get ...` | n/a | returns the admin password |
| 7 | Alex logs in | n/a | success |
| 8 | Provisioning runs (creates admin user, repos, etc.) | n/a | step 7.5 of `cove up` |

**What the user does:** install, run, log in.

**What `cove up` does internally (target state):**

```
cove up
├─ Pre-flight checks
│  ├─ ansible-playbook on PATH? else print: brew install ansible
│  ├─ docker on PATH? else print: brew install colima && colima start
│  ├─ colima running? else colima start
│  ├─ mkcert on PATH? else print: brew install mkcert && mkcert -install
│  ├─ ~/.config/cove/compose/ exists? else extract
│  ├─ ~/.config/cove/state/hostname.yml exists? else prompt for values OR auto-detect
│  └─ All checks pass? else exit 1 with clear errors
├─ Run ansible-playbook bringup.yml (renders templates, sets up /etc/hosts, pf NAT)
├─ Run ansible-playbook bootstrap_vault.yml (init + unseal + keychain)
├─ Run ansible-playbook provision_vault_user.yml (Vault user)
└─ Run ansible-playbook provision_forgejo.yml (admin user, repos)
```

**The "first run" experience needs to feel like one command.** Internal sub-steps are hidden. Failure modes print actionable messages.

**Sub-journey 1a: First run, Colima not started**

`cove up` should detect Colima isn't running, start it, wait for the docker context to be ready, then continue. The user should not have to `colima start` themselves. (Today, `bringup.yml` does this — line 15-31. We keep this.)

**Sub-journey 1b: First run, mkcert not installed**

`cove up` should detect mkcert is missing, print "Install: brew install mkcert && mkcert -install", and exit. The user installs, runs `cove up` again, and it works. (Today, `bringup.yml` silently skips if mkcert is missing, line 60-88. We make this fail loud.)

**Sub-journey 1c: First run, sudo required**

`cove up` needs sudo for /etc/hosts and pf NAT. The Ansible `-K` flag prompts for the sudo password. The user enters it once, it works.

**Sub-journey 1d: First run, no Tailscale**

This is fine — Tailscale is detected at runtime and skipped if not present. (Today, `bringup.yml` lines 33-57 check `tailscale status` and skip the rest of the Tailscale block if not running.)

**Sub-journey 1e: First run, with Tailscale**

The `ts_dns_name` is auto-detected from `tailscale status --json`. The Tailscale MagicDNS name becomes the external hostname; /etc/hosts is updated to point the Tailscale name to 127.0.0.1; tailscale serve is configured to forward 443 → 8443.

**Acceptance:** `cove up` succeeds for a first-time user who has the documented host prerequisites. The user sees at most 3 lines of output per step ("Starting Colima...", "Generating TLS cert...", "Bringing up containers...") and final URLs at the end.

## Journey 2 — Development loop (editing the compose tree)

Alex is developing cove itself. They have a checkout of the repo. They edit `compose/bringup.yml` and want to test it.

**Steps:**

| # | Step | Current | Target |
|---|------|---------|--------|
| 1 | Edit `compose/bringup.yml` | (yes) | (yes) |
| 2 | `cove up` | finds compose/ in repo, runs playbook | finds compose/ in repo (dev mode), runs playbook |
| 3 | Verify | Ansible runs from repo | Ansible runs from repo |

**Dev mode rule:** if `compose/inventory.yml` is found relative to CWD or git root, use it. This is the current `_find_compose_dir()` behavior. **Keep this exact behavior** in the new code. Dev mode is "use the repo, no extraction, no templating magic."

**The only change for dev mode:** the rendered `compose/.env`, `compose/nginx/default.conf`, and `compose/dnsmasq/cove.conf` are now written to `~/.config/cove/state/` instead of back into the repo tree. Wait, no — for dev mode, the existing behavior is convenient. If I'm iterating on the playbook I want to see the rendered nginx config. Hmm.

Let me think about this. Two options:

**Option 2a:** Dev mode writes rendered output to `~/.config/cove/state/rendered/` (the user state tree). Dev mode never writes to the repo.

**Option 2b:** Dev mode writes rendered output to the repo (as today), but uses `git status --ignored` to show the user what was rendered.

Option 2a is more consistent and the rendered output doesn't pollute the repo. The user can `cat ~/.config/cove/state/rendered/nginx/default.conf` to see it.

I'll go with 2a. The `compose/.gitignore` (or top-level `.gitignore`) gets entries for the rendered files, AND the CLI never writes them in dev mode either.

**Sub-journey 2a: Dev mode, no extraction**

In dev mode, the CLI must NOT extract resources on every `cove up`. It should use the repo directly. The detection is: CWD-or-git-root has `compose/inventory.yml` → use it. No extraction, no templates, no copy.

**Sub-journey 2b: Dev mode, with extraction (when? never)**

If Alex is in dev mode, they never need extraction. Extraction is a one-time thing for installed mode. If Alex wants to test extraction, they can run `cove init` explicitly.

**Acceptance:** `uv run --directory cli cove up` from the repo root brings up cove using the repo's `compose/` directory. No extraction. No `~/.config/cove/compose/`. The `compose/.env` and other rendered files go to `~/.config/cove/state/` (or `~/.config/cove/state/<hostname>/`).

## Journey 3 — Re-running `cove up` (idempotency)

Alex already has cove running. They want to make sure it's still up, or bring it up after a reboot.

**Steps:**

| # | Step | Current | Target |
|---|------|---------|--------|
| 1 | `cove up` | full playbook re-runs (mostly idempotent, but slow) | smart: check state, skip what doesn't need to run |
| 2 | Containers start (if down) | yes | yes |
| 3 | Re-provisioning runs (idempotent in theory, but verbose) | yes (unless --no-provision) | smarter: only re-provision if forced |

For the migration scope, I'll keep `cove up` running the full playbook sequence. The playbook is mostly idempotent (Ansible is good at this). The user can pass `--no-provision` to skip provisioning if they just want containers up.

**Sub-journey 3a: `cove up --no-provision`**

Useful for "containers are down but my Forgejo state is fine, just bring the containers back up." Today this is supported.

**Sub-journey 3b: `cove up` after `cove down`**

`cove down` runs `docker compose down` (no `--volumes` by default). The next `cove up` brings the containers back up with all their data. This already works.

**Sub-journey 3c: `cove up` after a reboot**

Colima auto-starts on macOS login. Forgejo data is in `~/Documents/cove-data/`. Certs are in `~/Documents/cove-data/certs/`. After reboot:
- `cove up` detects Colima is up, runs the playbook, /etc/hosts is preserved, pf NAT rule is preserved (we hope), certs are preserved, data is preserved. Everything just works.

**Acceptance:** `cove up` after a reboot brings cove back up with all data intact. The user might need to re-enter the sudo password (for the playbook `-K` flag).

## Journey 4 — Upgrading cove (new version installed)

A new version of cove-cli is published. Alex runs `uv tool upgrade cove-cli`. The new version is installed. The old `~/.config/cove/compose/` is on disk.

**What could break:**
- The `docker-compose.yml` syntax changed in the new version
- A new env var is required
- A new Ansible role is added
- A new file in `files/` is needed

**Target behavior:** On `cove up`, the CLI detects the installed version differs from the version in `~/.config/cove/compose/.version` and re-extracts resources. User data (certs, Forgejo repos, Vault data) is preserved.

**The version marker:** `~/.config/cove/compose/.version` is a file containing the cove-cli version that produced this extraction. The CLI compares it to its own `__version__`. Mismatch → re-extract.

**Sub-journey 4a: Schema migration**

If a new version requires migrating user data (e.g., Forgejo 14 → 15), the playbook handles it. This is out of scope for the stateless migration — it's a data migration concern.

**Sub-journey 4b: Config file changes**

If `group_vars/all.yml` adds a new variable, the user might want to set a value. The CLI could prompt or print a warning. For now: just re-extract and let Ansible fail loudly if a required var is missing.

**Acceptance:** `uv tool upgrade cove-cli && cove up` works without manual intervention for additive changes. Breaking changes (variable renamed, file moved) print a clear error and the user runs `cove init --force` to regenerate.

## Journey 5 — Teardown and uninstall

Alex wants to remove cove.

**Sub-journey 5a: `cove down`**

Stops containers, preserves all data. Today: `docker compose down`. Tomorrow: same.

**Sub-journey 5b: `cove down --volumes`**

Stops containers and removes Docker volumes. Destroys Forgejo and Vault data. Today: `docker compose down --volumes`. Tomorrow: same.

**Sub-journey 5c: `cove uninstall`**

- Stops containers
- Removes `~/.cache/cove/`
- Removes keychain entries
- Strips AGENTS.md guidance
- Removes `~/.config/cove/`? **No** — that contains the user's cove config. Add a `--purge-config` flag for the nuke case.

**Sub-journey 5d: `cove uninstall --purge-config --purge-data`**

- Everything in 5c
- Removes `~/.config/cove/`
- Removes `~/Documents/cove-data/`

**Sub-journey 5e: `uv tool uninstall cove-cli`**

- Removes the CLI binary
- Does NOT touch `~/.config/cove/` or `~/Documents/cove-data/`
- Does NOT touch /etc/hosts or pf NAT or keychain

This is fine — the user can re-install later and pick up where they left off. The user explicitly removes the rest if they want a clean slate.

**Acceptance:** `cove down`, `cove uninstall`, and `uv tool uninstall cove-cli` all do exactly what they say and no more. The user can `cove down; cove up` to bounce the platform. The user can `cove uninstall; cove install` to refresh agent guidance. The user can `uv tool uninstall cove-cli` to remove the CLI without losing data.

## Journey 6 — New host, same person

Alex gets a new Mac. They want cove there too.

**Steps:**

| # | Step | Notes |
|---|------|-------|
| 1 | Install Homebrew, uv, git | OS setup |
| 2 | `uv tool install cove-cli` | installed mode |
| 3 | `brew install ansible colima mkcert` | host prereqs |
| 4 | `colima start && mkcert -install` | one-time |
| 5 | `cove up` | extracts, runs, done |
| 6 | Login to https://git.cove/ | done |

**The Tailscale question:** on the new host, does Alex have Tailscale set up the same way? Maybe, maybe not. The bringup playbook auto-detects and either uses Tailscale (with the local DNS name) or skips it.

**The data question:** Alex wants their old Forgejo repos. They have two options:
- rsync `~/Documents/cove-data/` from old to new Mac
- Or start fresh (lose old repos, new ones are clean)

This is out of scope for the stateless migration. Data portability is a separate concern.

**Acceptance:** A new Mac with `cove up` is functional within 5 minutes of `uv tool install cove-cli` (assuming host prereqs are met).

## Journey 7 — Multiple installs (dev + prod)

This is a stretch. Alex wants to test a new cove-cli version side-by-side with the stable version.

**How it might work:**
- `uv tool install cove-cli` (stable)
- `uv tool install --with cove-cli cove-cli@dev` (or some other mechanism for the dev version)
- `cove-dev up` runs the dev version, `cove up` runs the stable

This requires two `~/.config/cove/` trees. Maybe `~/.config/cove/` is versioned by default: `~/.config/cove/0.1.0/`, `~/.config/cove/0.2.0/`. The CLI uses `~/.config/cove/<current-version>/`.

**For now, defer this journey.** Single-version is the only target. Multiple installs is a future problem.

## What I'm trying to nail down

Looking at the journeys, the must-haves for the migration are:

1. **First run works** with no `compose/` in the working directory.
2. **Dev mode unchanged** — repo-based workflow still works.
3. **Re-extraction on version change** — `uv tool upgrade cove-cli` doesn't strand old `~/.config/cove/`.
4. **Idempotent** — `cove up` after a `cove down` works.
5. **Clean teardown** — `cove uninstall` doesn't leave detritus; `uv tool uninstall` doesn't touch data.
6. **No PII in tracked files** — the repo is publishable.

The nice-to-haves (defer):
- Multiple versions side-by-side
- Data portability (rsync) helpers
- GUI launcher (separate concern)
- Config schema validation

OK, next musing: the actual mechanism. Where do files go, how do paths resolve, what gets bundled.
