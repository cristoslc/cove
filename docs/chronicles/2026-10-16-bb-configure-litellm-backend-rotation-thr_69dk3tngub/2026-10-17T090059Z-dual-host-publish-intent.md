---
type: intent
timestamp: 2026-10-17T090059Z
responding-to: annotated v0.14.0 tag and stable installation were verified locally
---

## Publish 0.14.0 to both forges

**Responding to:** annotated `v0.14.0` points to release commit `628df29`; the stable CLI reports version 0.14.0 from the verified wheel.

Per operator request: run `scripts/release.sh 0.14.0`, which pushes the tag to `origin` and `github`, publishes the wheel and release notes on GitHub, then publishes the wheel and notes on Forgejo. Success means each host independently shows the expected tag, release, and wheel asset. Stop if either publisher half fails; do not push `github/main`.

**Commits in this unit:** none yet
