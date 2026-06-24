# `fj pr view` Syntax Confusion

## The Problem

Agents (and humans) keep getting `fj pr view` syntax wrong. The recurring failure mode:

1. Agent needs to view PR comments → tries `fj pr view 13 --comments` (wrong flag)
2. Agent concludes "fj CLI doesn't have a way to list comments" → falls back to Forgejo API
3. The correct command was always `fj pr view 13 comments` — a positional subcommand, not a flag

This has happened repeatedly across different agents and different tasks. The pattern is always the same: the agent tries `gh`-style syntax, fails, and either invents a workaround or asks for help.

## Root Cause Analysis

### 1. `gh` is the dominant mental model

GitHub CLI (`gh`) is the most widely used forge CLI. Its command structure is:

```
gh pr diff 12          # top-level subcommand
gh pr view 12          # view is just one subcommand
gh pr checks 12        # another top-level subcommand
```

In `gh`, `pr` has many direct subcommands: `diff`, `view`, `checks`, `review`, `status`, etc. Each takes the PR number as an argument.

Forgejo CLI (`fj`) nests inspection commands under `view`:

```
fj pr view 12 diff     # diff is a subcommand of view
fj pr view 12 comments # comments is a subcommand of view
fj pr view 12 files    # files is a subcommand of view
```

This is the inverse of `gh`. Agents trained on `gh` patterns will naturally try `fj pr diff 12` or `fj pr comments 13`.

### 2. The guidance was incomplete

The old `fj-guide.md` table listed only `diff`, `files`, and `commits` under PRs. The `comments` subcommand was entirely absent. When an agent scanned the table and didn't see "comments", it reasonably concluded the feature didn't exist.

### 3. The subcommand nesting note was buried

There was a prose paragraph about subcommand nesting, but it was easy to miss when scanning for a specific command. Tables are scanned first; prose is secondary.

## What Good Guidance Looks Like

### Pattern-first, not command-list-first

Instead of a flat table, lead with the pattern:

```
fj pr view <ID> <action>
```

Then list ALL valid actions in one place. This teaches the *rule*, not just individual commands.

### Explicit "wrong" examples

Show the common mistake alongside the correction:

```
WRONG: fj pr diff 12          # "diff" is not a subcommand of "fj pr"
RIGHT: fj pr view 12 diff     # "diff" is a subcommand of "fj pr view"

WRONG: fj pr view 13 --comments  # --comments is not a flag
RIGHT: fj pr view 13 comments    # "comments" is a positional subcommand
```

### Complete action inventory

List every `fj pr view` subcommand in one place so agents can find any action at a glance:

| Action | Command |
|--------|---------|
| View body | `fj pr view <ID> body` |
| View comments | `fj pr view <ID> comments` |
| View specific comment | `fj pr view <ID> comment <N>` |
| View diff | `fj pr view <ID> diff` |
| View diff (patch) | `fj pr view <ID> diff --patch` |
| View files changed | `fj pr view <ID> files` |
| View commits | `fj pr view <ID> commits` |
| View labels | `fj pr view <ID> labels` |

### `gh` → `fj` mapping table

A direct translation table helps agents trained on `gh`:

| `gh` command | `fj` equivalent |
|---|---|
| `gh pr view 12` | `fj pr view 12` |
| `gh pr diff 12` | `fj pr view 12 diff` |
| `gh pr view 12 --comments` | `fj pr view 12 comments` |
| `gh pr diff 12 --patch` | `fj pr view 12 diff --patch` |
| `gh pr view 12 --files` | `fj pr view 12 files` |
| `gh pr view 12 --commits` | `fj pr view 12 commits` |

## Recommendation

Restructure the PR section of `fj-guide.md` to:

1. Lead with the `fj pr view <ID> <action>` pattern
2. List ALL view subcommands in a complete table
3. Add a `gh` → `fj` mapping section
4. Add explicit WRONG/RIGHT examples
5. Keep the prose note about nesting but make it a callout

This addresses all three root causes: the `gh` mental model trap, the incomplete command inventory, and the buried prose.
