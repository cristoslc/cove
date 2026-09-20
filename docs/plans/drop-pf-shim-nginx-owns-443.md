# Plan: drop the pf shim — nginx binds 443 directly

**Sashay source:** docs/tech-debt/2026-09-19-cove-status-missing-443-pf-check.md
**Decision (operator, 2026-09-19):** pf is the fragile layer; drop the shim. nginx owns 443 directly; tailscale serve is removed; status probes 443.

## Problem

Ingress rides a pf rdr shim (127.0.0.1:443 → 8443). Any VPN client can disable
pf and silently kill `https://git.cove` while `cove status` stays green
(status probes 8443 only). Surfshark's WireGuard reconnect did this on
2026-09-19.

## Changes

1. **compose/docker-compose.yml**: nginx ports `0.0.0.0:${NGINX_HTTPS_PORT:-8443}:443`
   → `0.0.0.0:443:443` (keep `80:80`).
2. **compose/bringup.yml**: delete the pf-rdr step (~line 312) and the
   tailscale-serve step (~line 149) so `cove up` cannot resurrect either.
3. **cli/cove/status.py**: `NGINX_HTTPS_PORT = 8443` → `443`.
4. **Tests**: update/add unit tests covering status port and any bringup
   assertions on the deleted steps; follow Mandatory Test Suite Standards
   (failing test first where behavior changes).

## Acceptance

- HTTPS push to `git.cove` works with pf **disabled** and Surfshark
  reconnecting at will.
- `cove status` green when 443 works, red when not.

## Cutover (live stack, operator-assisted — sudo)

1. Snapshot `~/.config/cove/compose/` (not git-tracked — no safety net).
2. `tailscale serve reset`; confirm `*:443` free (`sudo lsof -i :443`).
3. Reinstall `cove` from merged wheel (post-merge promote step only).
4. `cove down && cove up` (sudo); verify 443 probe + `https://git.cove` 200 +
   `git push origin` with pf disabled.
   Rollback = restore snapshot.

## Sequence

Branch + worktree → chronicle + draft PR → subagent implements → closure loop
(rebase, test gate, code review, staging e2e) → operator review → merge →
promote (reinstall `cove`) → live cutover → retro.

## Constraints

- Promote (wheel rebuild + `uv tool install --force`) is post-merge only.
- `cove down/up` and pf toggling are sudo tasks: operator-assisted.
- Docs (`~/.agents/.../cove.md`) already say nginx owns 443; this change makes
  the doc true. The pf check suggested in the tech-debt doc becomes moot.