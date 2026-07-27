# Muse: `*.cove` → `*.cove.local` for locally-hosted Cove services

## The idea

Rename all locally-hosted Cove service domains from `*.cove` to `*.cove.local` — e.g., `git.cove` → `git.cove.local`, `vault.cove` → `vault.cove.local`, etc.

## Current state

All Cove services live under the bare `.cove` pseudo-TLD:

| Service | Current domain |
|---|---|
| Forgejo | `git.cove` |
| Vault | `vault.cove` |
| LiteLLM | `litellm.cove` |
| Health check | `hc.cove` |
| CA redirect | `ca.cove` |
| Pages | `*.pages.cove` |
| Per-machine | `*.cove.<hostname>` |

DNS: `/etc/resolver/cove` → dnsmasq (`address=/cove/127.0.0.1`) → `127.0.0.1`
TLS: Wildcard cert with SAN `*.cove` + all named subdomains
Git remotes: 12+ repos across `~/code/` and `~/projects/` point to `git.cove`

## The real problem: browsers treat `.cove` as a search term

This is the killer issue. Browsers use the **Public Suffix List (PSL)** to decide whether something typed in the URL bar is a domain name or a search query. `.cove` is not on the PSL, so typing `git.cove` sends it to Google instead of navigating there. You have to type `https://git.cove` or `git.cove/` every time.

`.local` **is** on the PSL as a reserved special-use domain (RFC 6762). Browsers recognize `*.cove.local` as a valid domain and navigate to it directly. This is the single strongest argument for the change.

## Pros

1. **Browser URL bar works** — `git.cove.local` navigates immediately instead of searching. This is the daily friction that makes the change worth considering.

2. **Explicit locality** — `.cove.local` self-documents that these are LAN-only services. No ambiguity about whether `git.cove` is a real internet domain.

3. **Reserved-suffix safety** — `.local` is reserved by IANA (RFC 6762, mDNS/Bonjour). `.cove` is a pseudo-TLD with no registration, but nothing prevents someone from someday registering a real `.cove` TLD. `.cove.local` is structurally immune to collision.

4. **Cleaner namespace for future public services** — If Cove ever exposes services on the real internet (e.g., `git.cove.dev`, `pages.cove.dev`), the split is obvious: `.cove.local` = local, `.cove.dev` = public. With `.cove` as local, you'd need a different scheme for public.

5. **DNS mechanism unchanged** — macOS `/etc/resolver/` works identically with any suffix. Just rename the file to `/etc/resolver/cove.local` and update the dnsmasq pattern to `address=/cove.local/127.0.0.1`.

6. **Convention alignment** — `.local` is the de facto standard for local network services (Bonjour, Avahi, RFC 6762). Many dev tools (Docker, Kubernetes, Vagrant) use `.local` or `.localhost` variants.

## Cons

1. **Massive migration surface** — The cove repo alone has `.cove` references in:
   - nginx config + Jinja2 template (6 server blocks + 4 regex blocks)
   - Ansible playbook (`bringup.yml`: cert SANs, hosts file, env vars, health checks)
   - Docker compose env vars
   - Python CLI (`status.py`, `litellm.py`, `vault_cache.py`, `vault_unseal.py`, `project.py`)
   - Jinja2 project templates
   - All test files (certs, DNS, CLI, vault, litellm)
   - All docs (README, fj-guide, litellm-proxy, ADRs)
   - Staging scripts
   - DNS config templates for all platforms (macOS, Linux, Windows, iOS, Android)
   - CHANGELOG.md

   Rough estimate: 40-50 files, hundreds of individual references.

2. **External repo churn** — 12+ repos with git remotes pointing to `git.cove`. Each needs:
   - `git remote set-url` on every remote
   - AGENTS.md updates (documented remotes)
   - Any hardcoded URLs in docs or code
   - Any credential helper configs

3. **Git remote breakage** — Until all repos update their remotes, `git fetch/push` silently fails or uses stale URLs. Transition period requires both domains to work simultaneously.

4. **mDNS collision risk** — `.local` is already used by mDNS/Bonjour. macOS's `/etc/resolver/cove.local` takes precedence for `*.cove.local` queries, so this should work — but there's a real risk of confusion when debugging DNS issues. `dscacheutil -q host -a name git.cove.local` might return mDNS results instead of dnsmasq results if the resolver config is wrong.

5. **Typing tax** — `.cove.local` is 5 more characters than `.cove`. For daily commands like `git clone git@git.cove.local:...`, `curl https://git.cove.local/...`, `fj login git.cove.local`, this adds up. Minor but real friction.

6. **Per-machine subdomain complexity** — `*.cove.<hostname>` becomes `*.cove.local.<hostname>`, which is getting long. `git.cove.local.my-macbook` is 28 characters vs `git.cove.my-macbook` at 20.

## Migration strategy (if we proceed)

### Phase 1: Dual support (additive, no breakage)

1. Add `*.cove.local` SANs to the wildcard cert alongside existing `*.cove` SANs
2. Add `server_name` aliases in nginx for all `*.cove.local` variants
3. Add `address=/cove.local/127.0.0.1` to dnsmasq config
4. Add `cove.local` to `/etc/hosts` entries
5. Update CLI health checks to try both Host headers
6. Everything continues to work with both domains

### Phase 2: Primary domain migration

1. Change all cove repo defaults to `*.cove.local`
2. Update all Python code, templates, docs, tests
3. Keep `*.cove` as fallback/alias
4. Regenerate cert with `*.cove.local` as primary, `*.cove` as secondary SAN

### Phase 3: External repo updates

1. Script: find all repos with `git.cove` remotes, update to `git.cove.local`
2. Update AGENTS.md in each repo
3. Update any hardcoded URLs in docs/code

### Phase 4: Deprecation

1. Remove `*.cove` from cert SANs
2. Remove `*.cove` nginx server blocks
3. Remove `*.cove` from dnsmasq
4. Remove `*.cove` from `/etc/hosts`
5. Document the change in CHANGELOG

## Verdict

**Worth doing, but needs a careful phased approach.**

The browser URL bar friction is real daily pain — typing `git.cove` searches instead of navigating. `.local` is on the PSL, so `git.cove.local` navigates immediately. That alone justifies the migration cost.

The migration is large but mechanical: ~40-50 files in the cove repo + 12 external repos with git remotes. The phased approach (dual support → primary migration → external updates → deprecation) keeps things working throughout.

Key open questions:
- `.local` has mDNS collision risk — macOS's `/etc/resolver/cove.local` should take precedence, but need to verify `dscacheutil` behavior and test that mDNS doesn't interfere
- The typing tax is real: `.cove.local` is 5 more chars than `.cove`. Mitigations: browser bookmarks, shell aliases, `cove` CLI shortcuts
- Per-machine subdomains get long: `git.cove.local.my-macbook` vs `git.cove.my-macbook`. Consider dropping the per-machine pattern entirely or using a shorter convention
