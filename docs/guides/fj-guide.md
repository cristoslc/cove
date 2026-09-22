# Forgejo CLI (`fj`) Guide

## Draft PRs via Title Convention

Forgejo determines draft/pull-request state from the PR title:

- **Draft:** title starts with `WIP:` (case-insensitive) — PR cannot be merged
- **Ready:** title does **not** start with `WIP:`

## Commands

| Action | Command |
|--------|---------|
| Create draft PR | `fj pr create "WIP: <title>"` |
| Mark ready | `fj pr edit <PR> title "<title>"` (remove `WIP:` prefix) |
| Mark draft | `fj pr edit <PR> title "WIP: <title>"` (add `WIP:` prefix) |
| Check status | `fj pr view <PR>` (title prefix tells you) |

## Issues

| Action | Command |
|--------|---------|
| Create (with body file) | `fj issue create "Title" --body-file <path>` |
| Create (editor) | `fj issue create` — opens `$EDITOR` for title + body |
| Comment | `fj issue comment <ID> --body-file <path>` |
| Edit title | `fj issue edit <ID> title "New title"` |
| Assign | `fj issue assign <ID> <username>` |
| Unassign | `fj issue unassign <ID> <username>` |
| List | `fj issue list` |
| View | `fj issue view <ID>` |
| Search | `fj issue search [query]` |
| Close | `fj issue close <ID>` |

## Pull Requests

### The Core Pattern

```
fj pr view <ID> <action>
```

**All inspection actions are subcommands of `fj pr view`**, not of `fj pr`. The PR ID goes **before** the action. This is the inverse of `gh`, where actions are top-level subcommands of `gh pr`.

### Complete Action Inventory

| Action | Command |
|--------|---------|
| Create draft PR | `fj pr create "WIP: <title>"` |
| Mark ready | `fj pr edit <PR> title "<title>"` (remove `WIP:` prefix) |
| Mark draft | `fj pr edit <PR> title "WIP: <title>"` (add `WIP:` prefix) |
| Check status | `fj pr view <PR>` (title prefix tells you) |
| Comment | `fj pr comment <PR> --body-file <path>` |
| Merge | `fj pr merge <PR>` | Fails if title starts with `WIP:` — remove prefix first |
| Search | `fj pr search [query] [--state open\|closed\|all]` |
| **View body** | `fj pr view <ID> body` |
| **View comments** | `fj pr view <ID> comments` |
| **View specific comment** | `fj pr view <ID> comment <N>` |
| **View diff** | `fj pr view <ID> diff` |
| **View diff (patch)** | `fj pr view <ID> diff --patch` |
| **View files changed** | `fj pr view <ID> files` |
| **View commits** | `fj pr view <ID> commits` |
| **View labels** | `fj pr view <ID> labels` |

### Common Mistakes

```
WRONG: fj pr diff 12              # "diff" is not a subcommand of "fj pr"
RIGHT: fj pr view 12 diff         # "diff" is a subcommand of "fj pr view"

WRONG: fj pr view 13 --comments   # --comments is not a flag
RIGHT: fj pr view 13 comments     # "comments" is a positional subcommand

WRONG: fj pr comments 13          # "comments" is not a subcommand of "fj pr"
RIGHT: fj pr view 13 comments     # "comments" is under "fj pr view"

WRONG: fj pr files 12             # "files" is not a subcommand of "fj pr"
RIGHT: fj pr view 12 files        # "files" is under "fj pr view"
```

### `gh` → `fj` Mapping

If you know `gh`, use this translation table:

| `gh` command | `fj` equivalent |
|---|---|
| `gh pr view 12` | `fj pr view 12` |
| `gh pr diff 12` | `fj pr view 12 diff` |
| `gh pr diff 12 --patch` | `fj pr view 12 diff --patch` |
| `gh pr view 12 --comments` | `fj pr view 12 comments` |
| `gh pr view 12 --files` | `fj pr view 12 files` |
| `gh pr view 12 --commits` | `fj pr view 12 commits` |
| `gh pr view 12 --labels` | `fj pr view 12 labels` |

**Key difference:** In `gh`, inspection actions are flags on `gh pr view` or top-level subcommands of `gh pr`. In `fj`, they are all positional subcommands of `fj pr view`. The PR ID always comes **before** the action in `fj`.

**Important:** `fj issue create` does **not** have a `--title` flag — title is the first positional argument. For body text, always prefer `--body-file` over `--body` (see [docs/musings/fj-issue-create-body-file.md](docs/musings/fj-issue-create-body-file.md) for rationale). This applies to **all** `--body-file`-compatible commands (`fj issue comment`, `fj pr comment`).

**`fj pr create` title is positional, not `--title`:** Like `fj issue create`, `fj pr create` takes the title as its first positional argument. There is **no** `--title` flag — `fj pr create --title "WIP: foo"` fails with `error: unexpected argument '--title' found`. Use `fj pr create "WIP: <title>"` instead.

**`fj pr create` requires `--body-file` (no `$EDITOR` fallback):** When no `--body` or `--body-file` is provided, `fj pr create` attempts to open `$EDITOR` to compose the body. If `$EDITOR` is unset, the command fails (see Troubleshooting). Always pass `--body-file <path>` — this is the preferred Cove pattern and avoids the editor dependency entirely. As a fallback for interactive use, set `EDITOR=vim` in your shell environment.

## Repos

| Action | Command |
|--------|---------|
| Create | `fj repo create <name>` — **currently broken** (see [Troubleshooting](#fj-repo-create-alphadashdot-validation-error)), use the [API workaround](#create-a-repo-via-the-forgejo-api) instead |
| List | `fj repo list` |
| View | `fj repo view <owner>/<name>` |

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `error: unexpected argument '--title' found` | `fj pr create` has no `--title` flag; title is the first positional argument | Pass the title positionally: `fj pr create "WIP: <title>"` |
| `fj pr create` fails when no `--body`/`--body-file` is given, with an editor-related error | `$EDITOR` is unset, and `fj pr create` tries to launch it for body input | Always use `--body-file <path>` (preferred). For interactive fallback, set `EDITOR=vim` in your shell |
| `error: unrecognized subcommand 'diff'` | Diff is a subcommand of `fj pr view`, not `fj pr` | Use `fj pr view <PR> diff` (PR ID before the subcommand) |
| `error: unexpected argument '--comments' found` | `--comments` is not a flag; it's a positional subcommand of `fj pr view` | Use `fj pr view <PR> comments` (no `--` prefix) |
| `error: unrecognized subcommand 'comments'` (on `fj pr`) | `comments` is a subcommand of `fj pr view`, not `fj pr` | Use `fj pr view <PR> comments` |
| `error: unrecognized subcommand 'files'` (on `fj pr`) | `files` is a subcommand of `fj pr view`, not `fj pr` | Use `fj pr view <PR> files` |

## Authentication & Token Management

`fj` manages two token types, both stored in
`~/Library/Application Support/Cyborus.forgejo-cli/keys.json`:

- **OAuth token** (default): `fj auth login` opens a browser OAuth flow against
  Forgejo and stores a short-lived access token (~1 hour) plus a long-lived
  refresh token (~30 days) in `keys.json`.
- **Application token**: `fj auth add-token` creates a long-lived personal
  access token (valid until revoked). Use when OAuth is impractical (headless,
  CI) or as a fallback.

### Git pushes use the OAuth helper, not GCM alone

`git push`/`pull` over HTTPS to `git.cove` or `git.cove.local` must go through
**`git-credential-oauth`** chained with **Git Credential Manager (GCM)** —
not GCM's Generic provider by itself. The Generic provider returns cached
OAuth access tokens verbatim with no expiry check, so pushes start failing
with "Credentials are incorrect or have expired" roughly an hour after
`fj auth login` (diagnosis in
[docs/musings/gcm-oauth-token-expiry.md](../musings/gcm-oauth-token-expiry.md)).
`git-credential-oauth` performs the OAuth flow itself and refreshes expired
tokens; GCM provides the keychain storage.

Required global git config for **both** hostnames (`git.cove` and
`git.cove.local` — the legacy and local-domain forms; both must carry the
helper chain, since the helper config is keyed per-host):

```shell
# Storage (once, global)
git config --global credential.helper /usr/local/share/gcm-core/git-credential-manager

# Per-host OAuth helper chain — repeat for git.cove and git.cove.local
for h in git.cove git.cove.local git.cove.local:8443; do
  git config --global "credential.https://${h}.helper" oauth
  git config --global --add "credential.https://${h}.helper" osxkeychain
  git config --global "credential.https://${h}.oauthAuthURL" /login/oauth/authorize
  git config --global "credential.https://${h}.oauthTokenURL" /login/oauth/access_token
  git config --global "credential.https://${h}.oauthClientID" a4792ccc-144e-407e-86c9-5e7d8d9c3269
done
```

- The `oauthClientID` is Forgejo's client ID for the git credential flow —
  provisioned by `cove up`; do not invent a different value.
- `credential.https://<host>.helper` is a **multi-valued** key: `oauth`
  runs first (fetch/refresh), `osxkeychain` stores the result.
- Verify with:
  `echo "protocol=https\nhost=git.cove\n" | git credential fill` — it should
  return a current token without prompting. Repeat with `host=git.cove.local`.

### Scripting against the API

Do **not** scrape `keys.json` in scripts when a Vault-backed token exists.
Retrieve the application token via the Cove credential helpers (see
[the API workaround below](#create-a-repo-via-the-forgejo-api)):
`cove creds vault-get forgejo-token`. Reading `keys.json` with `jq` is only
for interactive inspection.

## Cove-Specific Conventions

- `fj` is aliased in the interactive shell — use `zsh -i -c 'fj ...'` when running from non-interactive contexts (e.g., agent sessions, scripts).
- All Cove git remotes point to `https://git.cove.local/` (Forgejo). Use `fj` for PR management, not `gh`.
- Draft PRs from plans **MUST** have a `WIP: ` title prefix and be created in draft status (per AGENTS.md).
- Every commit on a sashay PR **MUST** be immediately followed by a PR chronicle comment via `fj pr comment`.

## Troubleshooting

### `fj repo create` AlphaDashDot validation error

`fj repo create <name>` fails for **any** repo name with:

```
validation failed: [Name]: AlphaDashDot
```

This is an **upstream `fj` bug** (not a Cove bug) — the `fj` client sends the
repo name in a field that Forgejo's `AlphaDashDot` validator rejects. Until the
upstream fix lands, create repos via the Forgejo API directly.

### Create a repo via the Forgejo API

Use the Forgejo REST API to create a repo, bypassing the broken `fj` subcommand:

```shell
curl -X POST https://git.cove.local/api/v1/user/repos \
  -H "Authorization: token <token>" \
  -H "Content-Type: application/json" \
  -d '{"name":"repo-name"}'
```

**Retrieving the token:** prefer the Vault-backed helper
(`cove creds vault-get forgejo-token`) — see
[Authentication & Token Management](#authentication--token-management). For
interactive inspection only, `fj` stores its auth token at
`~/Library/Application Support/Cyborus.forgejo-cli/keys.json` (the `token` field
of the active host entry); read it with `jq`:

```shell
jq -r '.hosts["git.cove.local"].token' \
  ~/Library/Application\ Support/Cyborus.forgejo-cli/keys.json
```

Do **NOT** hardcode the token in docs, scripts, or commits. For long-term
automation, store it in Vault and retrieve it with the Cove credential helpers:

```shell
cove creds vault-get forgejo-token
cove creds vault-put forgejo-token
```

After creating the repo, add it as a remote per the
[Cove conventions](#cove-specific-conventions): `origin` for the primary remote,
`fj` for the Forgejo secondary remote (HTTPS, not SSH).
