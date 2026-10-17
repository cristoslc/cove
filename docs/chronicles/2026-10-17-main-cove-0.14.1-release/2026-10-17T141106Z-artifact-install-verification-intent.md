---
type: intent
timestamp: 2026-10-17T141106Z
responding-to: scripts/release.sh 0.14.1 completed successfully
---

## Verify both release assets and install the released wheel

**Responding to:** `scripts/release.sh 0.14.1` pushed the annotated tag and created releases on GitHub and Forgejo.

Per operator request: independently download the wheel from each release, compare each byte-for-byte with the clean local wheel, verify both release notes and tag targets, then reinstall the stable uv tool from the verified release wheel and check its reported version. Do not run Cove lifecycle commands.

**Commits in this unit:** none yet
