---
type: intent
timestamp: 2026-10-17T085948Z
responding-to: fresh main gate and clean 0.14.0 wheel verification passed
---

## Commit and push release metadata

**Responding to:** merged main passed the required gate, and the rebuilt wheel passed version, overlay-helper, and no-nested-build checks.

Per operator request: commit the 0.14.0 changelog, project version, lock version, and local release chronicle entries; include any tracked resource-sync changes if present, then push only `main` to `origin`. Success means a clean pushed release commit on Forgejo with the new wheel built from that commit's source state; do not push `github/main`.

**Commits in this unit:** none yet
