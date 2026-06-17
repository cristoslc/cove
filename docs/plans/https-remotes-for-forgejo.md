# HTTPS as Default Forgejo Remote Transport

## Problem

Cove's agent guidance and provisioning default to SSH git remotes (`git@forgejo-localhost:...`) for local Forgejo, but HTTPS (`https://git.cove/...`) is the canonical entrypoint. This creates a hard dependency on a specific SSH key, bypasses the nginx+mkcert TLS front door, and conflicts with the `cove-push` token credential helper flow already set up for HTTPS.

## Changes

### 1. `cli/cove/templates/fj-reference.md.j2` (line 20)

Replace the SSH remote detection paragraph with an HTTPS-first version. SSH becomes an optional footnote.

**Before:**
```
`fj` reads the git remote URL from the current repo. Local Cove remotes use `git@forgejo-localhost:cristos/repo.git` — the `forgejo-localhost` SSH config alias handles routing to `localhost:2222` with the correct SSH key.
```

**After:**
```
`fj` reads the git remote URL from the current repo. Local Cove remotes use `https://git.cove/<owner>/<repo>.git`. The `cove-push` token in git's credential helper handles auth (set up by `cove up`).

SSH (`git@forgejo-localhost:...`) is also available as an optional transport — see `~/.agents/agents-md-detail/cove.md` for SSH config details.
```

### 2. `cli/cove/templates/detail-cove.md.j2` (lines 11-23)

Demote the SSH config section from a top-level subsection to an optional note. Replace the dedicated "SSH config setup" section with a brief mention under the Forgejo section.

**Before:**
```
### SSH config setup

`cove up` generates `~/.ssh/config.d/forgejo-localhost.conf`:

```
Host forgejo-localhost
  HostName localhost
  Port 2222
  User git
  IdentityFile ~/.ssh/forgejo_{{ computer_name }}_ed25519
  IdentityAgent none
  IdentitiesOnly yes
```
```

**After:**
```
SSH is available as an optional transport. `cove up` generates `~/.ssh/config.d/forgejo-localhost.conf` with a dedicated key at `~/.ssh/forgejo_{{ computer_name }}_ed25519` for users who need SSH.
```

Also update the architecture table to note SSH is optional.

### 3. `compose/provision_forgejo.yml` (lines 332-345 and 362)

- Line 332-345: Keep the SSH config write task but add a comment noting it's optional. The task is harmless and useful for users who want SSH.
- Line 362: The `git remote add cove` URL is already `{{ forgejo_root_url }}{{ repo_owner }}/{{ repo_name }}` which resolves to HTTPS — this is already correct. No change needed.

### 4. `cli/cove/project.py` (line 70)

The `_render_agents_block` function already says "All git remotes go to Forgejo" without specifying SSH — this is already correct. No change needed.

### 5. `cli/cove/templates/project-guidance.md.j2`

Already generic, no SSH mention. No change needed.

## Files to modify

1. `cli/cove/templates/fj-reference.md.j2` — SSH → HTTPS in remote detection paragraph
2. `cli/cove/templates/detail-cove.md.j2` — Demote SSH config section

## Files verified as already correct (no changes)

- `cli/cove/project.py` — "All git remotes go to Forgejo" is transport-agnostic
- `cli/cove/templates/project-guidance.md.j2` — no SSH mention
- `compose/provision_forgejo.yml` — remote add URL already uses `forgejo_root_url` (HTTPS); SSH config task is optional infrastructure

## Testing

- `cove install -g` regenerates spoke docs with HTTPS as default
- `cove up` provisioning playbook adds remotes as HTTPS (already correct)
- No project-level AGENTS.md or spoke carries a `git@forgejo-localhost:...` default after re-install
