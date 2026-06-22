# Plan: Missing pre-checkout hook to enforce worktree discipline (#27)

## Issue
The global AGENTS.md mandates that the root of a project MUST always be on
main/trunk and all other branches MUST only live in `.worktrees/`. However,
there is no pre-checkout or post-checkout hook installed in `.git/hooks/` to
enforce this. An operator (or agent) can create a branch and commit directly
on the root, corrupting the trunk and interfering with parallel agents.

## Scope
Implement a git pre-checkout hook that rejects any checkout that would leave
the root directory on a non-main branch. Integrate the hook installation
into the Cove CLI (`cove init` or equivalent setup step).

## Tasks

### 1. Write a failing test for the hook enforcement
- Create `cli/tests/test_worktree_hook.py`
- Test that the hook rejects checkout to a non-main branch when in root
- Test that the hook allows checkout to main when in root
- Test that the hook allows checkout when inside `.worktrees/`

### 2. Implement the pre-checkout hook script
- Create `cli/cove/hooks/pre-checkout.sh` (or similar)
- The hook checks if the current working directory is the repo root (not
  inside `.worktrees/`)
- If in root and the target branch is not `main`/`master`/`trunk`, reject
  the checkout with an error message explaining worktree discipline
- If inside `.worktrees/`, allow any checkout
- If in root and target is `main`/`master`/`trunk`, allow the checkout

### 3. Implement hook installation in Cove CLI
- Add a `cove init` (or `cove hooks install`) command that installs the
  pre-checkout hook into `.git/hooks/`
- Alternatively, configure `core.hooksPath` to point to a hooks directory
- The installation should be idempotent (re-running doesn't break anything)

### 4. Document the hook in AGENTS.md and docs
- Update the project AGENTS.md to mention the hook
- Add a section to docs/ explaining worktree discipline enforcement

## Verification
- `uv run --directory cli pytest tests/ -v` — all tests pass
- Manual test: create a branch in root, verify it's rejected
- Manual test: create a worktree, verify checkout works inside it