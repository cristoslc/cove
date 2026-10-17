---
type: intent
timestamp: 2026-10-17T141014Z
responding-to: release metadata commit 77b25cc
---

## Push Forgejo main and tag the 0.14.1 release commit

**Responding to:** package, lock, changelog, and gate/build chronicle records are committed; release metadata commit is `77b25cc8a25a4d036e9f242fadb7c25180477a37`.

Per operator request: push the clean local main branch to Forgejo `origin` only, create annotated tag `v0.14.1` on the release metadata commit, and push that tag to `origin`. Success means Forgejo main contains the release and chronicle commits and the annotated tag points at the metadata commit; do not push `github/main`.

**Commits in this unit:** none yet
