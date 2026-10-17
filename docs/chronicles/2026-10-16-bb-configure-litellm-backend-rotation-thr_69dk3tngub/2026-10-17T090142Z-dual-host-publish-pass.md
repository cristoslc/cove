---
type: checkpoint
timestamp: 2026-10-17T090142Z
responding-to: dual-host publication was requested after tag and stable-install verification
---

## 0.14.0 published and verified on both hosts

**Responding to:** the operator requested publication to GitHub and Forgejo, then independent verification of each tag, release, and wheel asset.

Per operator request: `scripts/release.sh 0.14.0` succeeded. GitHub release `https://github.com/cristoslc/cove/releases/tag/v0.14.0` and Forgejo release `https://git.cove/cristos/cove/releases/tag/0.14.0` both list `cove_cli-0.14.0-py3-none-any.whl`; both remote annotated tags dereference to release commit `628df292e7e554aad1eb458606c69f63e6190d73`. I downloaded each wheel independently; local, GitHub, and Forgejo copies are byte-identical (249843 bytes, SHA-256 `71e9b0d4de2316d510285afd0b4fa0c92388174595c6e928bb34404e4ef60750`). `cove --version` reports 0.14.0. No GitHub main branch push was performed.

**Commits in this unit:** none yet
