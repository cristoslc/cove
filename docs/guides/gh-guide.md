# GitHub CLI (`gh`) Guide

## Draft / Ready Status

GitHub tracks draft status as a PR property (not title-based like Forgejo):

| Action | Command |
|--------|---------|
| Create draft PR | `gh pr create --draft` |
| Mark ready | `gh pr ready <PR>` |
| Mark draft | `gh pr ready <PR> --undo` |
| Check status | `gh pr view <PR> --json state,isDraft` |

## Pull Requests

| Action | Command |
|--------|---------|
| Create PR | `gh pr create --title "title" --body-file <path>` |
| Create draft PR | `gh pr create --draft --title "title" --body-file <path>` |
| View | `gh pr view <PR>` |
| List | `gh pr list` |
| Checkout | `gh pr checkout <PR>` |
| Merge | `gh pr merge <PR>` |
| Close | `gh pr close <PR>` |
| Reopen | `gh pr reopen <PR>` |
| Add reviewer | `gh pr edit <PR> --add-reviewer <handle>` |
| Add assignee | `gh pr edit <PR> --add-assignee <handle>` |
| Comment | `gh pr comment <PR> --body-file <path>` |
| Diff | `gh pr diff <PR>` — top-level subcommand (unlike `fj`, which nests it under `pr view`) |
| Diff (patch) | `gh pr diff <PR> --patch` |
| Diff (names only) | `gh pr diff <PR> --name-only` |
| Files changed | `gh pr view <PR> --json files --jq '.files[].path'` |
| Checks | `gh pr checks <PR>` |
| Search | `gh pr search [query]` |

## Issues

| Action | Command |
|--------|---------|
| Create | `gh issue create --title "title" --body-file <path>` |
| View | `gh issue view <ID>` |
| List | `gh issue list` |
| Comment | `gh issue comment <ID> --body-file <path>` |
| Close | `gh issue close <ID>` |
| Reopen | `gh issue reopen <ID>` |
| Edit title | `gh issue edit <ID> --title "New title"` |
| Assign | `gh issue edit <ID> --add-assignee <handle>` |
| Search | `gh issue search [query]` |

## CI / Actions

| Action | Command |
|--------|---------|
| View runs | `gh run list` |
| View run | `gh run view <run-id>` |
| View latest | `gh run view` |
| Watch | `gh run watch <run-id>` |
| Rerun | `gh run rerun <run-id>` |

## Auth

| Action | Command |
|--------|---------|
| Login | `gh auth login` |
| Status | `gh auth status` |
| Logout | `gh auth logout` |
| Switch account | `gh auth switch` |

## Repo

| Action | Command |
|--------|---------|
| Clone | `gh repo clone <owner>/<repo>` |
| Fork | `gh repo fork` |
| View | `gh repo view` |
| Create | `gh repo create <name>` |
