**Responding to:** operator instruction — update chronicle, then shutting down

Status update at shutdown (2026-09-20 ~04:35 ET):

**Done:**
- Implementation + review-fix commits on branch (`7c924d8` HEAD): compose 443,
  bringup pf/serve deletions, status.py 443, staging harness + e2e/staging
  tests moved to 443, dead NGINX_HTTPS_PORT export removed, 3 RGR guard tests
  (RED→GREEN). Gate after fix: 445 passed, 25 deselected.
- Code review loop ran once: 4 specialists + synthesis → needs_changes
  (1 high staging-8443, 2 medium, 3 low) → all addressed in 7c924d8.
- Rebase onto fjl/main: up to date (0 behind).

**Pending (next session, closure-loop steps 6→10):**
1. Re-run test gate post-rebase (was interrupted by shutdown: aborts during
   `uv run --directory cli pytest -m "not e2e and not staging"`; last full
   green was 445 on the same tree, so low risk).
2. Re-review (step 8 loop) — verify findings trend ↓ / clean.
3. Staging deploy + automated E2E via scripts/staging/ (tier-2 gate, -m staging).
4. Remove WIP: prefix → operator review (PR #50).

**Live cutover (after merge+promote, operator-assisted):** snapshot
~/.config/cove/compose/, `tailscale serve reset`, verify *:443 free, `cove
down && cove up` (sudo), verify 443 probe + https://git.cove 200 + push with
pf disabled. Standing hazard until then: VPN reconnect can kill pf again
(`pfctl -s info` first if HTTPS push times out).

Subagent task dirs cleaned (implement-pf-drop, fix-review-findings, fix
placeholder dispatch). Worktree .worktrees/drop-pf-shim-nginx-owns-443 left
intact for resumption. PR #50 stays WIP/draft.
