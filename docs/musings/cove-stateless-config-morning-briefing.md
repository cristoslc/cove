# Cove Stateless Config — Morning Briefing

**Date:** 2026-06-14 (rewritten 2026-06-19)
**Status:** All 5 phases implemented on branch `cove-stateless-config` (PR #22), code-reviewed, and e2e-verified against a parallel staging stack. PR #22 is ready for operator review.

## Prior attempt (PR #9 — closed without merging)

Phases 1–4 were implemented on branch `stateless-phase-2` (PR #9), but PR #9 was **closed without merging** and the branch was deleted. No phase work landed on `main`. The original "Phases 1–4 complete, end-to-end verified" claim described the closed branch, not merged state.

## Current sashay (PR #22 — open, draft)

**Branch:** `cove-stateless-config`
**PR:** https://git.cove/cristos/cove/pulls/22
**Base:** `main` @ `2a7eeca`

### Commits (13 total)

```
4312081 fix: e2e host_vars PII check scopes to admin_* fields, not paths
186b87d fix: e2e .env PII check scopes to var values, not file paths
684d1a7 fix: e2e PII checks scope to user PII only (hostname/ts_ip are by design)
680ceac fix: use dig +tcp for dnsmasq check (Colima doesn't forward UDP)
a427735 fix: staging e2e — retry dnsmasq dig, safe colima cleanup
5b88e9a feat: parameterize compose for parallel staging + e2e script
fabe32c test: add proper e2e fixture + branch-verification tests
5293803 fix: address remaining review findings — fail-loud, dead params, docs
64d2cd9 fix: address review findings — auto-init in cove up, hostname validation
2e6c9bd feat: stateless-config phase 5 — version re-extraction
351773b feat: stateless-config phase 4 — host vars auto-detection
274002a feat: stateless-config phase 3 — init + resolver
8b41483 feat: stateless-config phase 2 — bundle compose resources
96d97b2 feat: stateless-config phase 1 — PII cleanup
```

### What was implemented

**Phase 1 — PII cleanup:** Stripped `cristos` / `lc.cristos@gmail.com` / `MBPBK-202602` / `taila90e7` from tracked files. group_vars/all.yml admin_username/admin_email set to "" with assert in bringup.yml. Seeds converted to .example templates. .gitignore covers host_vars/*.yml, dnsmasq/cove.conf, seeds/*.yaml. test_no_pii.py guards against PII reappearance.

**Phase 2 — Bundle compose resources:** `cli/cove/resources/compose/` full PII-stripped copy. `cli/scripts/sync_compose_resources.py` syncs compose/ → resources/. pyproject.toml package-data `cove.resources = ["**/*"]`.

**Phase 3 — init + resolver:** `cli/cove/stateless.py` — resolve_compose_dir() (COVE_COMPOSE_DIR → CWD/compose → worktree → git-root → ~/.config/cove/compose → error), extract_resources(), ensure_init(), maybe_reextract(). `cove init` subcommand with --force/--purge. `cove up` auto-inits.

**Phase 4 — host vars auto-detection:** `cli/cove/state.py` — _detect_admin_username/email/op_vault/ts_dns_name from env vars + system. ensure_host_vars() writes `~/.config/cove/state/hosts/<hostname>.yml` (validated hostname, idempotent). bringup.yml's new `assert admin_username` task enforces non-empty.

**Phase 5 — version re-extraction:** maybe_reextract() checks `.version` stamp against `__version__`, re-extracts on mismatch. `cove up --no-upgrade` skips. `cove init --purge` removes entirely.

### Code review (4 specialist agents: security, style, logic, docs)

7 findings fixed across 2 commits (`64d2cd9`, `5293803`):
- LOGIC-HIGH: `cove up` didn't auto-init → fixed (ensure_init() call added)
- SECURITY-MEDIUM: hostname path traversal → fixed (regex validation)
- LOGIC-MEDIUM: COVE_COMPOSE_DIR silent fallthrough → fixed (raises now)
- STYLE-MEDIUM: _copy_resource reimplemented copytree → fixed (shutil.copytree)
- DOCS-MEDIUM: COVE_COMPOSE_DIR undiscoverable → fixed (help + example)
- STYLE-LOW: dead compose_dir param → fixed (removed)
- LOGIC-LOW: test_no_pii.py substring matching → fixed (startswith + self-path)

### E2E verification (staging stack, real `cove up`)

**Script:** `cli/tests/e2e_staging/run_staging_e2e.sh` (495 lines)
**Strategy:** Parallel staging stack on alt ports (8444/8081/2223/5354), alt container names (cove-staging-*), alt data root, staging HOME under `~/.cache/cove-staging/`. No sudo. `cove up --no-sudo --no-provision` runs the full Ansible flow.

**15 checks — ALL PASSED:**
- cove init extracts bundled resources (PII-free) ✓
- cove init is idempotent ✓
- maybe_reextract triggers on version mismatch ✓
- ensure_host_vars() wrote PII-free overlay during cove up ✓
- resolve_compose_dir() honors COVE_COMPOSE_DIR ✓
- resolve_compose_dir() raises on invalid COVE_COMPOSE_DIR ✓
- PII guard fires on injected PII ✓
- cove up --no-sudo --no-provision brought up staging stack ✓
- Staging containers (nginx, forgejo, vault, dnsmasq) running ✓
- Nginx serves HTTPS on staging port 8444 ✓
- Forgejo /api/healthz → 200 ✓
- Vault /v1/sys/health → 501 (sealed, expected) ✓
- dnsmasq resolves cove → 127.0.0.1 (via dig +tcp — Colima doesn't forward UDP) ✓
- Rendered configs (nginx, dnsmasq, .env, host_vars) user-PII-free ✓
- cove down tears down staging cleanly ✓

### Compose changes for staging support

- docker-compose.yml: nginx ports + dnsproxy container name env-var parameterized
- bringup.yml: skip vars (cove_skip_tailscale_serve, cove_skip_mkcert_install), docker_compose_v2 → shell docker compose, parameterized ports/pf/tailscale serve
- dnsmasq/Dockerfile: removed COPY cove.conf (config is volume-mounted at runtime)
- group_vars/all.yml: added dnsproxy_container_name

## Test count

| Stage | Tests | Notes |
|-------|-------|-------|
| Before | 115 | baseline (main) |
| Phase 1-5 | 148 | +33 new tests |
| E2e fixture | 173 | +25 packaging-layer e2e tests |
| Staging e2e | 15 checks | script-based, real `cove up` |

## Deferred work

1. **Provisioning path not e2e-tested**: `--no-provision` skips bootstrap_vault, provision_vault_user, provision_forgejo. Seed templating (vault-user.yaml from .example), vault unseal, forgejo admin creation untested. Requires 1Password creds or stubs.
2. **Sync script not wired to pre-commit**: `cli/scripts/sync_compose_resources.py` exists but not auto-run.
3. **`cove init` ansible-galaxy uses `check=False`**: silently ignores failures.
4. **Colima UDP limitation**: dnsmasq dig from host requires `+tcp` flag (Colima doesn't forward UDP). Affects prod too.
5. **Sync script + resources must be re-run** after any compose/ edit.

## Open items for operator review

1. **PR #22** is draft, ready for review. Remove `WIP:` prefix to mark ready for merge.
2. **Plan**: `docs/plans/cove-stateless-config.md` should be deleted after merge (all 5 phases complete).
3. **Morning briefing**: this file should be deleted after merge (descendent plan implemented).
4. **Cleanup**: worktree `.worktrees/cove-stateless-config` + branch `cove-stateless-config` after merge.