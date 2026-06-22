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

| Action | Command |
|--------|---------|
| Create draft PR | `fj pr create "WIP: <title>"` |
| Mark ready | `fj pr edit <PR> title "<title>"` (remove `WIP:` prefix) |
| Mark draft | `fj pr edit <PR> title "WIP: <title>"` (add `WIP:` prefix) |
| Check status | `fj pr view <PR>` (title prefix tells you) |
| Comment | `fj pr comment <PR> --body-file <path>` |
| Merge | `fj pr merge <PR>` | Fails if title starts with `WIP:` — remove prefix first |
| Search | `fj pr search [query] [--state open\|closed\|all]` |
| **Diff** | `fj pr view <PR> diff` — **NOT** `fj pr diff` (no such subcommand) |
| Diff (patch) | `fj pr view <PR> diff --patch` |
| Files changed | `fj pr view <PR> files` |
| Commits | `fj pr view <PR> commits` |

**Subcommand nesting:** Diff, files, and commits are subcommands of `fj pr view`, not of `fj pr`. The PR ID goes **before** the subcommand: `fj pr view 12 diff`, never `fj pr diff 12` (that fails with `error: unrecognized subcommand 'diff'`). The analogous `gh` command is top-level — `gh pr diff 12` — because GitHub's CLI surface differs from Forgejo's.

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

## Cove-Specific Conventions

- `fj` is aliased in the interactive shell — use `zsh -i -c 'fj ...'` when running from non-interactive contexts (e.g., agent sessions, scripts).
- All Cove git remotes point to `https://git.cove/` (Forgejo). Use `fj` for PR management, not `gh`.
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
curl -X POST https://git.cove/api/v1/user/repos \
  -H "Authorization: token <token>" \
  -H "Content-Type: application/json" \
  -d '{"name":"repo-name"}'
```

**Retrieving the token:** `fj` stores its auth token at
`~/Library/Application Support/Cyborus.forgejo-cli/keys.json` (the `token` field
of the active host entry). Read it with `jq`:

```shell
jq -r '.hosts["git.cove"].token' \
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
