# Plan: Phase 3 — External Repo Updates

## Motivation

Phase 2 changed Cove's default domain to `git.cove.local`, but 12+ repos across `~/code/` and `~/projects/` still have git remotes pointing to `git.cove`. These need updating so `git fetch/push` works without the old domain.

## Scope

Update all external repos that reference `*.cove` domains. This covers:

1. **Git remotes** — `git remote set-url` on every remote pointing to `git.cove`
2. **AGENTS.md** — Update documented remotes and URLs
3. **Hardcoded URLs** — Any `git.cove` or `vault.cove` references in docs, configs, or code
4. **SSH known_hosts** — Add new host key for `git.cove.local`, remove old `git.cove` entry
5. **Credential helper** — Update any `cove-push` token configs referencing old domain

## Repos to update

From the Phase 1 exploration, these repos have git remotes pointing to `git.cove`:

| Repo | Path | Remotes |
|------|------|---------|
| ai-harness-hooks | `~/code/ai-harness-hooks/` | `fj` (SSH) |
| ai-montage | `~/code/ai-montage/` | `origin` (SSH) |
| ai-usage-cost-analysis | `~/code/ai-usage-cost-analysis/` | `fj` (HTTPS) |
| opencode-ds4-proxy | `~/code/opencode-ds4-proxy/` | `fjl` (HTTPS) |
| orbic-rc400l-cli | `~/code/orbic-rc400l-cli/` | `fj`, `origin` (SSH) |
| swain-box | `~/code/swain-box/` | `origin` (HTTPS) |
| swain-phone | `~/code/swain-phone/` | `fj` (HTTPS) |
| swain-v2 | `~/code/swain-v2/` | `fjl` (SSH) |
| vendor-canary | `~/code/vendor-canary/` | `origin` (HTTPS) |
| common-bell-research | `~/projects/common-bell-research/` | `fjl` (HTTPS) |
| Project Hal | `~/projects/Project Hal/` | `origin` (HTTPS) |
| llm-data-export-manager | `~/projects/llm-data-export-manager/` | `origin` (SSH) |

## Implementation

### Script approach

Write a single script that handles all repos:

1. For each repo, find all remotes pointing to `git.cove`
2. `git remote set-url <name> <new-url>` replacing `git.cove` → `git.cove.local`
3. Update `AGENTS.md` if it references `git.cove` or `vault.cove`
4. Update any other hardcoded URLs in docs or config files

### SSH known_hosts

```bash
ssh-keygen -R git.cove 2>/dev/null
ssh-keyscan -H git.cove.local >> ~/.ssh/known_hosts 2>/dev/null
```

### Credential helper

Check `~/.config/git/config` and `~/.gitconfig` for any `git.cove` credential helper entries. Update to `git.cove.local`.

## Risks

- SSH host key mismatch will trigger a warning on first connection — the script should pre-accept the new key
- Some repos may have additional hardcoded URLs beyond git remotes (docs, configs) — need grep to find them
- Forgejo SSH port (2222) is unchanged, only the hostname changes
- HTTPS remotes use the `cove-push` token in git credential helper — the token is per-instance, not per-hostname, so it should still work

## Verification

After running the script, verify by:
1. `git fetch --all` in each repo
2. `grep -r "git.cove[^.]"` in each repo to catch any missed references
3. Run `cove status` to confirm DNS resolution shows `git.cove.local`
