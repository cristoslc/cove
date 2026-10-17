---
type: intent
timestamp: 2026-10-17T141033Z
responding-to: Forgejo main push and annotated v0.14.1 tag creation
---

## Publish the 0.14.1 release to both hosts

**Responding to:** main was pushed to Forgejo, and annotated tag `v0.14.1` points at release metadata commit `77b25cc`.

Per operator request: run `scripts/release.sh 0.14.1` to push the release tag and publish the verified wheel with changelog notes on GitHub and Forgejo. Success requires both release objects and assets to exist; stop if either publishing half fails. Do not push `github/main`.

**Commits in this unit:** none yet
