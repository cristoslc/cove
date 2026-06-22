# `fj` CLI auth vs git remote — default host blind spot

## Context

The repo `swain-phone` has two remotes:

| Remote  | URL                                      |
|---------|------------------------------------------|
| `origin`| `https://github.com/cristoslc/swain-phone.git` |
| `fj`    | `https://git.cove/cristos/swain-phone.git`     |

`main` tracks `origin/main`. The `fj` remote is the Cove/Forgejo mirror.

## The session

```
fj whoami                    # Error: not logged in
fj auth add-key cristos      # key: 3632... → success
fj whoami                    # cristos@github.com  ← works now
fj auth logout github.com    # signed out
fj auth add-key cristos      # key: 3632... → "key for git.cove already exists"
fj whoami                    # Error: not logged in  ← still broken
```

## What's actually happening

`fj` (the Forgejo CLI) has a **default host** — likely `codeberg.org` or whatever the upstream default is. Every command that omits `-H` targets that default, **not** the Cove instance at `https://git.cove`.

- `fj whoami` → checks default host → "not logged in" (correct — we never logged into codeberg.org)
- `fj auth add-key cristos` → adds key to **default host** → now default host has a key
- `fj whoami` → checks default host → "cristos@github.com" (the key we just added was for GitHub, so it resolves to that identity)
- `fj auth logout github.com` → logs out of default host
- `fj auth add-key cristos` → adds key to default host again → "key for git.cove already exists" — wait, this says **git.cove**, not codeberg.org

That last line is the puzzle. If `add-key` without `-H` targets the default host, why does it say "git.cove"? Two possibilities:

1. `fj` somehow infers the host from the remote URL in the current git repo (it sees `fj` remote → `https://git.cove`).
2. The default host was already set to `git.cove` via some config, and the earlier `fj whoami` failure was for a different reason.

If (1), then `fj` is context-aware for `add-key` but not for `whoami` — inconsistent behavior. If (2), then `whoami` failing after `add-key` succeeds means `add-key` stores a credential but doesn't register a session that `whoami` recognizes.

The `-H https://git.cove` test confirms the credential store works: `fj -H https://git.cove auth add-key cristos` says "key for git.cove already exists" — the key persisted. But `fj whoami` (even with `-H`) still fails after a fresh shell.

## Conclusion

`fj auth add-key` writes a long-lived credential (token file) that enables **git operations** (fetch/push to the `fj` remote). But `fj whoami` checks a **session store** that only `fj auth login` (OAuth flow) populates. They're two different auth systems under the same CLI:

- **`auth add-key`** → token store → enables git push/fetch
- **`whoami`** → session store → requires OAuth login

The `-H` flag is also critical: without it, every `fj` command targets the compiled-in default host, not the Cove instance. The `fj` remote in git config is irrelevant to `fj` CLI — the CLI doesn't read git remotes to determine its target host.
