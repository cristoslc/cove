---
type: final
timestamp: 2026-09-28T144800
responding-to: operator request — a `cove up --all` that launches every optional service
---

## Final — v0.9.0 promoted (`cove up --all`)

**Feature:** `cove up --all` launches every optional service with the default
pod. Runner starts with the bringup via `COMPOSE_PROFILES`; the LiteLLM and
Speedtest flows run after the provisioning chain because both need their
1Password/Vault credentials seeded into the compose `.env` before their
containers start (and `vault-get`/`vault-put` need Vault up). Tunnel excluded —
shares are created interactively. A credential failure on one optional is
reported without aborting (same contract as `cove status`).

**Course correction caught by the release process:** the feature was first
built against a stale checkout (v0.6.0-era, three releases behind `origin/main`,
which was already at v0.8.0 where ADE became a core service). The rebase
removed `ade` from the optional set everywhere — `--all` on the shipped code
covers Runner + LiteLLM + Speedtest, with ADE core.

- Gate: **624 passed / 28 deselected** (after rebase), pyright clean.
- Release commit `805268c`; annotated tag `v0.9.0`; promote per AGENTS.md.
- **Gap this exposed:** the tag was pushed to `origin` (git.cove) only — no
  GitHub tag/release/wheel. That drift is the subject of
  `docs/tech-debt/dual-host-release-drift.md` (closed same day, see the
  2026-09-28T155900 entry in this directory).
