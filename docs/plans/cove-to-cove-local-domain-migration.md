# Plan: `*.cove` → `*.cove.local` Domain Migration

## Motivation

Browsers use the Public Suffix List (PSL) to decide whether URL bar input is a domain or a search. `.cove` is not on the PSL, so typing `git.cove` searches instead of navigating. `.local` is a reserved PSL entry (RFC 6762), so `git.cove.local` navigates immediately. This is daily friction.

## Scope

Rename all locally-hosted Cove service domains from `*.cove` to `*.cove.local`:

| Service | Current | New |
|---|---|---|
| Forgejo | `git.cove` | `git.cove.local` |
| Vault | `vault.cove` | `vault.cove.local` |
| LiteLLM | `litellm.cove` | `litellm.cove.local` |
| Health check | `hc.cove` | `hc.cove.local` |
| CA redirect | `ca.cove` | `ca.cove.local` |
| Pages | `*.pages.cove` | `*.pages.cove.local` |
| Per-machine | `*.cove.<hostname>` | `*.cove.local.<hostname>` |
| Bare alias | `cove` | `cove.local` |

## Migration Strategy: Phased Dual-Support

### Phase 1: Dual Support (additive, no breakage)

Add `*.cove.local` alongside existing `*.cove` everywhere. Both work simultaneously.

**IMPORTANT:** Do NOT change Forgejo's internal config (`FORGEJO_DOMAIN`, `ROOT_URL`, `SSH_DOMAIN`) or Vault's `VAULT_ADDR` in this phase. Only add nginx-level routing, DNS, and cert SANs. Forgejo/Vault still think they live at `*.cove` — nginx handles the domain translation.

**Files to modify:**

1. **`compose/bringup.yml`** — Add `*.cove.local` SANs to TLS cert, add `cove.local` to `/etc/hosts`, add `cove.local` to dnsmasq config. Do NOT change Forgejo/Vault env vars yet.
2. **`compose/nginx/default.conf`** and **`default.conf.j2`** — Add `server_name` aliases for all `*.cove.local` variants
3. **`compose/dnsmasq/cove.conf.j2`** — Add `address=/cove.local/127.0.0.1`
4. **`compose/bringup.yml`** — Update TLS cert validation (lines 202-214) to accept both old and new hostnames
5. **`cli/cove/status.py`** — Update health checks to try both Host headers; update DNS check to accept either domain
6. **`cli/cove/litellm.py`** — Update health checks
7. **DNS config templates** — Update all platform DNS scripts to include `*.cove.local.<hostname>`
8. **`scripts/staging/setup.sh`** — Update health check
9. **Test files** — Update test assertions to accept both domains

### Phase 2: Primary Domain Migration

Change all defaults to `*.cove.local`. Keep `*.cove` as fallback/alias.

**This phase changes Forgejo's internal config:**
- `FORGEJO_DOMAIN=git.cove.local`
- `FORGEJO_ROOT_URL=https://git.cove.local/`
- `FORGEJO_SSH_DOMAIN=git.cove.local`
- Requires Forgejo restart (handled by `docker compose restart forgejo`)

**Also changes Vault's config:**
- `VAULT_ADDR=https://vault.cove.local/`

**Also updates:**
- `cli/cove/vault_cache.py` — Update default VAULT_ADDR
- `cli/cove/vault_unseal.py` — Update default VAULT_ADDR
- `cli/cove/project.py` — Update project scaffolding templates
- `cli/cove/templates/*.j2` — Update template references
- `compose/group_vars/all.yml` — Update domain vars
- `compose/docker-compose.yml` — Update env vars

**SSH host key handling:** Before this phase, update `~/.ssh/known_hosts` to remove old `git.cove` entry. The migration script should do this.

**Webhooks/OAuth:** Document that any registered webhooks or OAuth apps pointing to `git.cove` need manual reconfiguration. Forgejo does not support bulk URL replacement.

### Phase 3: External Repo Updates

Script to find and update all repos with `git.cove` remotes to `git.cove.local`. Also update `~/.ssh/known_hosts` to add the new host key.

### Phase 4: Deprecation

Remove `*.cove` from cert SANs, nginx, dnsmasq, hosts file.

## Key Decisions

- **mDNS collision:** `.local` is reserved for mDNS (Bonjour/Avahi). macOS `/etc/resolver/cove.local` takes precedence for `*.cove.local` queries, so this should work. Verify with `dscacheutil` after deployment.
- **Per-machine subdomains:** `git.cove.local.<hostname>` is long (28 chars). Acceptable — these are auto-generated, not typed manually.
- **Typing tax:** `.cove.local` is 5 more chars. Mitigate with browser bookmarks, shell aliases, and `cove` CLI shortcuts.
- **Git remote breakage:** Phase 1 dual support means old remotes still work during transition. Phase 3 updates all remotes.

## Risks

- mDNS interference with `.local` resolution
- Missed references in external repos
- Stale credential helper configs pointing to old domain
- Forgejo SSH host key mismatch after domain change
