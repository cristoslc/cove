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

**Important:** `fj issue create` does **not** have a `--title` flag — title is the first positional argument. For body text, always prefer `--body-file` over `--body` (see [docs/musings/fj-issue-create-body-file.md](docs/musings/fj-issue-create-body-file.md) for rationale). This applies to **all** `--body-file`-compatible commands (`fj issue comment`, `fj pr comment`).

## Cove-Specific Conventions

- `fj` is aliased in the interactive shell — use `zsh -i -c 'fj ...'` when running from non-interactive contexts (e.g., agent sessions, scripts).
- All Cove git remotes point to `https://git.cove/` (Forgejo). Use `fj` for PR management, not `gh`.
- Draft PRs from plans **MUST** have a `WIP: ` title prefix and be created in draft status (per AGENTS.md).
- Every commit on a sashay PR **MUST** be immediately followed by a PR chronicle comment via `fj pr comment`.
