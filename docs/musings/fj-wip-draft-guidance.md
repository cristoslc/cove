---
title: "fj WIP/Draft Guidance for Cove Install"
created: 2026-06-14
status: Draft
---

# fj WIP/Draft Guidance for Cove Install

## Problem

Cove's AGENTS.md says draft PRs must have a `WIP:` title prefix, and the PR sashay workflow depends on creating draft PRs and later marking them ready for review. But `fj` (the Forgejo CLI) doesn't have a `--draft` flag. Forgejo uses the `WIP:` title prefix convention — a PR is draft if and only if its title starts with `WIP:`.

This needs to be documented in Cove's install/setup guidance so that anyone using `fj` on a Cove instance knows how to manage draft state.

## How Forgejo Draft PRs Work

Forgejo determines draft status from the PR title:

- **Draft:** title starts with `WIP:` (case-insensitive) — the PR cannot be merged, and Forgejo blocks merge attempts
- **Ready for review:** title does NOT start with `WIP:` — the PR can be merged normally

There is no separate `draft` boolean field. The title prefix IS the draft flag.

## fj Commands

### Create a draft PR (WIP)

```bash
fj pr create "WIP: implement multi-stage sync"
```

The `WIP:` prefix makes it a draft. Forgejo blocks merges on draft PRs.

### Move from draft to ready for review

```bash
fj pr edit <PR> title "implement multi-stage sync"
```

Remove the `WIP:` prefix from the title. The PR is now ready for review and can be merged.

### Move from ready back to draft

```bash
fj pr edit <PR> title "WIP: implement multi-stage sync"
```

Add the `WIP:` prefix back. The PR becomes a draft again.

### Check draft status

```bash
fj pr view <PR>
```

The output shows the title. If it starts with `WIP:`, it's a draft.

## Cove-Specific Conventions

Per AGENTS.md, draft PRs from sashay plans **must** have a `WIP:` title prefix and be created in draft status. The workflow is:

1. **Create:** `fj pr create "WIP: <descriptive title>"` — draft by convention
2. **Work:** Push commits, add PR chronicle comments
3. **Ready:** `fj pr edit <PR> title "<descriptive title>"` — remove `WIP:`
4. **Back to draft (if needed):** `fj pr edit <PR> title "WIP: <descriptive title>"` — add `WIP:` back

## What Needs to Change

The Cove install/setup guidance should include a section on `fj` usage that covers:

1. How to install `fj` (if not already in the Cove provision)
2. How to authenticate `fj` against the local Forgejo instance
3. How to create draft PRs (the `WIP:` prefix convention)
4. How to transition PRs between draft and ready (edit title to add/remove `WIP:`)
5. Common `fj` commands for the Cove workflow (create PR, view PR, comment, merge)

This should live wherever Cove's post-install guidance lives — likely in a README section or a `docs/fj-guide.md` that AGENTS.md references.