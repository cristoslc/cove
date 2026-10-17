---
type: intent
timestamp: 2026-10-17T090159Z
responding-to: dual-host release verification passed
---

## Persist the release chronicle

**Responding to:** GitHub and Forgejo releases, tags, and wheel assets are verified, and the stable CLI reports version 0.14.0.

Per operator request: commit the release action entries already projected to PR #63 as a documentation-only commit and push that commit to Forgejo `origin/main`. Success means the worktree is clean, release tag `v0.14.0` still points to `628df29`, and no GitHub main branch was pushed.

**Commits in this unit:** none yet
