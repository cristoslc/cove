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

## Cove-Specific Conventions

- `fj` is aliased in the interactive shell — use `zsh -i -c 'fj ...'` when running from non-interactive contexts (e.g., agent sessions, scripts).
- All Cove git remotes point to `https://git.cove/` (Forgejo). Use `fj` for PR management, not `gh`.
- Draft PRs from plans **MUST** have a `WIP: ` title prefix and be created in draft status (per AGENTS.md).
- Every commit on a sashay PR **MUST** be immediately followed by a PR chronicle comment via `fj pr comment`.
