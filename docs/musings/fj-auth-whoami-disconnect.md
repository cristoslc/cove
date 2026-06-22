# `fj` CLI auth — default host, git remote inference, and empty-token corruption

## Context

The repo `swain-phone` has two remotes:

| Remote  | URL                                      |
|---------|------------------------------------------|
| `origin`| `https://github.com/cristoslc/swain-phone.git` |
| `fj`    | `https://git.cove/cristos/swain-phone.git`     |

`main` tracks `origin/main`. The `fj` remote is the Cove/Forgejo mirror.

## The session (annotated with what's actually happening)

```
fj whoami                    # Error: not logged in
```

`fj` infers the host from git remotes → finds `fj` remote → extracts `git.cove` → looks in `~/.config/forgejo-cli/keys.json` for `git.cove` → no entry yet → "not logged in".

```
fj auth add-key cristos
new key: 3632690a299c3579b1475f31c8953dddaf86eea1
```

`add-key` also infers `git.cove` from git remotes → creates entry in keys.json with token. But `fj`'s **default host** (when no git remote inference applies, or for `whoami`) is `github.com` — this is documented in the [forgejo-cli wiki](https://codeberg.org/Cyborus/forgejo-cli/wiki/Authentication) and confirmed by a [blog post](https://blog.n-daisuke897.com/posts/2026-02-01-operating-self-hosted-forgejo-via-cli-a-forgejo-cli-guide-2/): "Note that you must specify the host with `-H git.example.com`; otherwise, it defaults to `github.com`."

```
fj whoami
currently signed in to cristos@github.com
```

`whoami` uses the **default host** (`github.com`), not the git-remote-inferred host. It finds no entry for `github.com` (we added to `git.cove`), so... wait, it says "cristos@github.com". This means either: (a) `whoami` also infers from git remotes but displays the host differently, or (b) the first `add-key` actually targeted `github.com` (the default) despite the git remote inference.

The keys.json on disk tells the real story:

```json
{
  "hosts": {
    "codeberg.org": { "type": "OAuth", "name": "cristoslc", "token": "eyJ..." },
    "cove.local:8443": { "type": "Application", "name": "cristos", "token": "3632690a299c3579b1475f31c8953dddaf86eea1" },
    "git.cove": { "type": "Application", "name": "cristos", "token": "" }
  },
  "aliases": {
    "git.cove:2222": "git.cove",
    "localhost:2222": "cove.local:8443"
  }
}
```

Key observations:
- `cove.local:8443` has the valid token `3632690a299c3579b1475f31c8953dddaf86eea1`
- `git.cove` has an **empty token** — the user pressed Enter at the "new key:" prompt on the second `add-key` call
- `fj auth list` shows `cristos@git.cove` despite the empty token — it doesn't validate, just reads stored entries
- `fj whoami` also doesn't validate the token — it reads the stored username from the matched entry

```
fj auth logout github.com
fj auth add-key cristos
new key:                     ← user pressed Enter (empty!)
key for git.cove already exists
```

The "key for git.cove already exists" confirms `add-key` inferred `git.cove` from the git remote. But since the user pressed Enter without pasting a token, it set the token to `""`, corrupting the entry.

```
fj whoami
Error: not logged in
```

`whoami` found the `git.cove` entry but with an empty token → treated as "not logged in". (Or it used the default host `github.com` which was logged out.)

## How `fj` determines the host

Three mechanisms, with confusingly different behavior:

1. **Default host**: `github.com` (compiled-in). Used when no git remote inference applies.
2. **Git remote inference**: `fj` reads `.git/config` remotes, extracts the hostname from the URL. Used by `add-key`, `whoami`, and most commands — but `whoami` may fall back to default host differently than `add-key`.
3. **`-H` flag**: Explicit override. Always works correctly.

The [wiki](https://codeberg.org/Cyborus/forgejo-cli/wiki/Authentication) says: "If your current directory is a git repository with a remote on a Forgejo instance, it will try to log in on that instance." But the blog post contradicts this for `add-key`, saying it defaults to `github.com` without `-H`.

## Token storage

Keys live at `~/Library/Application Support/Cyborus.forgejo-cli/keys.json` on macOS. The file is plain JSON, no encryption. Entries have `type: "Application"` (for `add-key`) or `type: "OAuth"` (for `auth login`). Neither `whoami` nor `auth list` validate tokens — they just display stored metadata.

## Workarounds

**Always use `-H https://git.cove`** with every `fj` command. This is the only reliable way to target the Cove instance. Without it, you're at the mercy of default host vs git remote inference, which behave differently per subcommand.

**Never press Enter at the key prompt.** An empty token silently corrupts the entry. If you do this, delete the entry from keys.json and re-add with the correct token.

**Alternatives to `fj`:**
- **[`fgj`](https://codeberg.org/romaintb/fgj)** — a `gh`-like CLI for Forgejo with a clean `~/.config/fgj/config.yaml` that explicitly lists hosts, tokens, and users. No git remote inference magic. Drop-in replacement philosophy.
- **[`forgejo-cli-ex`](https://github.com/JKamsker/forgejo-cli-ex)** — extends `fj` with UI endpoint access, reads the same keys.json. Same auth model, more features.
- **[`codeberg-cli`](https://pypi.org/project/codeberg-cli/)** — Python-based, works with any Forgejo instance. Clean config in `config.toml`.
- **Thin API wrapper** — Forgejo has a well-documented REST API at `/api/v1`. A simple bash/curl wrapper or a small Rust binary would avoid `fj`'s auth confusion entirely. The API uses `Authorization: token <sha1>` headers.

## Verdict

`fj` is **not fundamentally broken**, but its auth UX is confusing due to:
1. Default host (`github.com`) vs git remote inference — inconsistent per subcommand
2. No token validation in `whoami` or `auth list` — shows stale/empty entries
3. Silent corruption on empty key input
4. `-H` required but easy to forget

For Cove's purposes, the simplest path is **always use `-H https://git.cove`** and treat `fj` as a thin API client, not a smart context-aware tool. If the confusion persists, a thin curl wrapper around the Forgejo API would be ~50 lines and eliminate the auth layer entirely.
