# Plan: fj WIP/Draft PR Guidance for Cove Install

## Summary

Add Forgejo CLI (`fj`) WIP/draft PR guidance to Cove's documentation so users know how to manage draft PR state on a Cove Forgejo instance.

## Tasks

- [ ] Create `docs/fj-guide.md` with:
  - How Forgejo draft PRs work (WIP: title prefix convention)
  - `fj pr create "WIP: <title>"` for draft PRs
  - `fj pr edit <PR> title "<title>"` to mark ready
  - `fj pr edit <PR> title "WIP: <title>"` to mark draft again
  - `fj pr view <PR>` to check status
  - Cove-specific conventions per AGENTS.md
- [ ] Add reference to `docs/fj-guide.md` in README.md (new "Forgejo CLI" section or under Install)
- [ ] Add reference to `docs/fj-guide.md` in AGENTS.md (Cove-specific notes section)
