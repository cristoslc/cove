# fj — Forgejo CLI Reference

## Invocation

```bash
fj <command> <subcommand> [options]
```

`fj` auto-detects the Forgejo host from the project's git remote URL (configured as `http://localhost:3000/`). No `-H` flag, no alias, no shell wrapper needed.

## What `fj` does NOT handle

Use `git` directly for operations `fj` does not support:

| Operation | Command |
|-----------|---------|
| Push / pull / fetch | `git push` / `git pull` / `git fetch` |
| Commit / amend | `git commit` / `git commit --amend` |
| Clone | `git clone http://localhost:3000/owner/repo.git` |
| Branch / checkout / merge | `git branch` / `git checkout` / `git merge` |
| Rebase / stash | `git rebase` / `git stash` |
| Remote management | `git remote add` / `git remote set-url` |

## Subcommand reference

### repo — Repository management

| Subcommand | Description |
|------------|-------------|
| `repo create <name>` | Create a new repository |
| `repo fork <name>` | Fork a repository |
| `repo migrate <url>` | Migrate a repository from another forge |
| `repo view [<name>]` | View repository info (defaults to current repo) |
| `repo readme [<name>]` | View repository README |
| `repo clone <name>` | Clone a repository |
| `repo star <name>` | Star a repository |
| `repo unstar <name>` | Unstar a repository |
| `repo delete <name>` | Delete a repository |
| `repo browse <name>` | Open repository in browser |
| `repo labels` | Manage issue labels |
| `repo edit <name>` | Edit repository properties |
| `repo units` | Manage repository units (wiki, issues, etc.) |

### issue — Issue tracking

| Subcommand | Description |
|------------|-------------|
| `issue create <title>` | Create an issue |
| `issue edit <id>` | Edit an issue |
| `issue comment <id>` | Add a comment on an issue |
| `issue assign <id> <user>` | Assign users to an issue |
| `issue unassign <id> <user>` | Unassign users from an issue |
| `issue close <id>` | Close an issue |
| `issue search [query]` | Search issues (use `--state open/closed/all`) |
| `issue view <id>` | View issue details |
| `issue templates` | List issue templates |
| `issue browse <id>` | Open issue in browser |

**Flags:** `--remote <name>` to specify the git remote, `-r` / `--repo <owner/name>` for repo name.

### pr — Pull requests

| Subcommand | Description |
|------------|-------------|
| `pr search [query]` | Search pull requests (use `--state open/closed/all`) |
| `pr create <title>` | Create a pull request (prefix `WIP:` for draft) |
| `pr view <id>` | View pull request details |
| `pr status <id>` | Check mergability and CI status |
| `pr checkout <id>` | Checkout a PR as a local branch |
| `pr comment <id>` | Add a comment on a PR |
| `pr assign <id> <user>` | Assign users to a PR |
| `pr unassign <id> <user>` | Unassign users from a PR |
| `pr edit <id>` | Edit PR title or body |
| `pr close <id>` | Close a PR without merging |
| `pr merge <id>` | Merge a PR |
| `pr browse <id>` | Open PR in browser |

**PR creation:** Use `--base <branch>` and `--head <branch>` to specify branches. Use `--body "<text>"` or `--body-file <path>` for the body. Draft PRs start with `WIP:` in the title.

### actions — CI / Woodpecker

| Subcommand | Description |
|------------|-------------|
| `actions tasks` | List CI tasks on a repo |
| `actions variables` | List and manage CI variables |
| `actions secrets` | Manage CI secrets |
| `actions dispatch` | Dispatch a workflow run |

### release — Releases

| Subcommand | Description |
|------------|-------------|
| `release create <tag>` | Create a release |
| `release edit <id>` | Edit a release |
| `release delete <id>` | Delete a release |
| `release list` | List all releases |
| `release view <id>` | View release details |
| `release browse <id>` | Open release in browser |
| `release asset` | Manage release assets |

### tag — Git tags

| Subcommand | Description |
|------------|-------------|
| `tag create <name>` | Create a tag on Forgejo (use `git tag` for local) |
| `tag delete <name>` | Delete a tag |
| `tag list` | List tags |
| `tag view <name>` | View tag details |

### wiki — Wiki

| Subcommand | Description |
|------------|-------------|
| `wiki contents` | List wiki pages |
| `wiki view <page>` | View a wiki page |
| `wiki clone` | Clone the wiki repo |
| `wiki browse` | Open wiki in browser |

### auth — Authentication

| Subcommand | Description |
|------------|-------------|
| `auth login` | Log in to an instance |
| `auth logout` | Log out from an instance |
| `auth add-key` | Add an application token for an instance |
| `auth use-ssh` | Configure SSH authentication |
| `auth list` | List logged-in instances |

### Other commands

| Command | Description |
|---------|-------------|
| `whoami` | Show current authenticated user |
| `user` | User operations |
| `org` | Organization operations |
| `version` | Show fj version |
| `completion <shell>` | Generate shell completion scripts |

## Common workflows

| Task | Command |
|------|---------|
| View current repo | `fj repo view` |
| View an issue | `fj issue view <id>` |
| Search open issues | `fj issue search --state open` |
| Create a PR | `fj pr create --base main --head <branch> "title"` |
| Check PR status | `fj pr status <id>` |
| List releases | `fj release list` |
| Check CI status | `fj actions tasks` |
| List open PRs | `fj pr search --state open` |