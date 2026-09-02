# extract_resources() deletes runtime .env on promote (compose re-extraction)

**Date:** 2026-09-02 (discovered during PR #46 promote, issue #44 sashay)
**Severity:** high (silent data-mount failure on promote + recreate; recovery required manual .env rebuild)
**Component:** `cli/cove/stateless.py` — `extract_resources()` / `maybe_reextract()`

## Problem

`extract_resources()` uses `shutil.rmtree(target)` on the deployed compose dir
(`~/.config/cove/compose/`) whenever the bundled content hash changes, then re-copies
the bundle. This deletes the runtime `.env` — the file holding
`COVE_DATA_ROOT`, `FORGEJO_DATA_ROOT`, speedtest/litellm secrets, etc.

AGENTS.md and `bringup.yml` treat the `.env` as first-boot-only; the docs (written in
PR #46) assumed a promote would leave it in place. In reality every promote that
changes compose resources wipes it.

**Failure chain (observed live, 2026-09-02):**

1. Promote → `cove init` → rmtree + re-extract → `.env` gone.
2. Operator/agent runs `docker compose up -d forgejo` per the documented
   promote-path instructions → compose warns `FORGEJO_DATA_ROOT variable is not
   set, defaulting to a blank string` → bind-mounts a fresh empty path
   (`/forgejo/gitea` inside the colima VM) → Forgejo boots with an **empty
   database** (0 users, 0 repos) with no hard error. The real data at
   `~/Documents/cove-data/forgejo/` was intact; the container was just
   pointed at a fresh mount.
3. `cove up` cannot repair non-interactively (BECOME password prompt), and the
   blank-string warning is easy to miss in normal docker output.

## Recovery performed (2026-09-02)

Rebuilt `.env` from bringup's first-boot render contract (values from
`group_vars/all.yml`, live container env for speedtest/litellm secrets, and the new
`FORGEJO_WEBHOOK_ALLOWED_HOST_LIST=loopback`), then `docker compose up -d
--force-recreate forgejo`. Verified: 3 users, 57 repos, API auth 200, webhook var
present. Data was never lost — the wrong mount was empty, not the real one.

## Fix direction

- In `extract_resources()`, preserve runtime-managed files across re-extraction:
  at minimum `.env` (consider also anything under a `secrets/` or local-only
  allowlist). Move them aside before rmtree, restore after copy.
- Add a warning at compose-up time in the CLI when `FORGEJO_DATA_ROOT`/
  `COVE_DATA_ROOT` are unset (fail loud instead of blank-string default).
- Update `docs/services/forgejo.md` promote-path wording: a promote deletes the
  runtime `.env`; the next `cove up` re-renders it (needs BECOME).
- Tests: unit test that `extract_resources(force=True)` preserves a pre-existing
  `.env`; adversarial test that compose up with blank data-root fails loudly.