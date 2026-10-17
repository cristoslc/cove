---
type: checkpoint
timestamp: 2026-10-17T141159Z
responding-to: release artifact verification and stable tool install intent
---

## Cove 0.14.1 published on both hosts and installed

**Responding to:** the operator required independent release verification, byte-identical wheel downloads, and stable tool installation only after the gate.

Per operator request: `scripts/release.sh 0.14.1` succeeded on GitHub and Forgejo. Both remote annotated tags point to release commit `77b25cc8a25a4d036e9f242fadb7c25180477a37`; both release pages contain the wheel and the same two fixed notes. The local, GitHub-downloaded, and Forgejo-downloaded wheels are byte-identical, each SHA-256 `aa98695849c65b742d659d5ff5329aa974f04c21f692b89de37ff5108e2f8586`.

The stable uv tool was installed from the verified local release wheel; `cove --version` reports `0.14.1`. The installed uv requires a wheel path as the package argument, so the direct local-wheel form was used. No Cove lifecycle command, extraction, deployment, E2E, release reinstall from an unverified source, or `github/main` push ran.

**Commits in this unit:** 77b25cc
