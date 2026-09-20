# Tech Debt: Cove ingress rides a pf shim that any VPN client can disarm — green while `https://git.cove` is dead

**Filed:** 2026-09-19
**Severity:** Medium (primary documented ingress endpoint fails while status reports healthy)
**Status:** Open — decision made 2026-09-19: **drop the pf shim entirely; nginx binds 443 directly** (plan below)

## Decision (2026-09-19, post-diagnosis)

Operator decision: pf is the fragile layer — on macOS any VPN client (here:
Surfshark's WireGuard PacketTunnel reconnect) owns the pf enable/disable switch,
so ingress behind an rdr shim is hostage to unrelated reconnects. Tailscale is
not an option for remote access going forward (operator decision). The
permanent shape:

1. **nginx owns 443 directly**: compose nginx ports `0.0.0.0:443:443` (keep
   `80:80`). Unprivileged low-port binds work here — Colima's ssh mux already
   binds `*:80`. tailscaled's `*:443` listener must be freed first or nginx's
   bind fails.
2. **Remove tailscale serve**: `tailscale serve reset`. Cove HTTPS becomes
   nginx-only.
3. **bringup.yml**: delete the pf-rdr step (~line 312) and the tailscale-serve
   step (~line 155) so `cove up` cannot resurrect either.
4. **pf**: leave alone — enabled/disabled no longer matters to cove.
5. **cove-cli**: `status.py` `NGINX_HTTPS_PORT = 8443` → 443 (edit in the cove
   source repo if installed from one, then reinstall — not in the venv).
6. Snapshot `~/.config/cove/compose/` first (not git-tracked — no safety net),
   then `cove down && cove up`, verify 443 probe + `https://git.cove` 200 +
   `git push origin` with pf still disabled. Rollback = restore snapshot.
   Brief Forgejo/nginx downtime during recreate.

Acceptance: HTTPS push to `git.cove` works with pf **disabled** and Surfshark
reconnecting at will; `cove status` green when 443 works and red when not.

## Problem

On 2026-09-19 (~23:00 ET) `git push origin` (HTTPS `git.cove`) timed out on port
443 while `cove status` had been reporting green. Root cause, confirmed by
diagnosis:

- **Surfshark's WireGuard PacketTunnel system extension disabled pf when it
  reconnected at ~20:30** (`pfctl -s info`: "Status: Disabled for 0 days
  02:37:56", matching the extension's 8:33PM reconnect). With pf off, cove's
  rdr anchor (443→8443, verified present: `rdr pass on lo0 inet proto tcp from
  any to 127.0.0.1 port = 443 -> 127.0.0.1 port 8443`) went inert.
- With pf off, 127.0.0.1:443 fell through to tailscaled's own `*:443` listener
  (root-owned, invisible to unprivileged lsof), which does not answer IPv4
  loopback — connections **timed out** (dropped) rather than refused. Control
  probes: `::1:443` ✓, `100.116.166.31:443` ✓ (tailscale IP), `127.0.0.1:8443`
  ✓, `127.0.0.1:443` ✗ timeout — a purely address-specific black hole.
- `cove up` (run by operator mid-diagnosis) did NOT restore pf — bringup's pf
  step self-skips when the rule text is already in the anchor (bringup.yml:317
  greps `pfctl -s nat`, which still listed the rule; it doesn't check enabled
  state).
- Fix: `sudo pfctl -E` → 443 probe green, `https://git.cove` HTTP 200, push
  succeeded. `cove status` had remained green throughout (it probes 8443
  directly, per status.py `NGINX_HTTPS_PORT = 8443`).
- Earlier red herrings: Surfshark kill switch (already off), quitting Surfshark
  entirely (extension unloaded, 443 still broken — dropped packets came from
  pf being disabled, not the VPN filter), Surfshark TransparentProxy/Antivirus
  extensions (present but not the dropper once pf was off).

## Why status missed it

`cove status` (cove-cli `cove/status.py`) checks containers, nginx ingress on
**8443** directly, Forgejo/Vault APIs, and DNS. It never:

1. probes `127.0.0.1:443` (the port `https://git.cove` actually uses), or
2. verifies **pf enabled state** — `pfctl -s info` Status line — not just the
   rdr rule text. The rule can sit in the anchor while pf is disabled
   (Surfshark's WireGuard reconnect did exactly that on 2026-09-19), and
   `cove up`'s own self-skip (grep the nat list, not the enabled flag) means
   re-running bringup does not recover either.

## Suggested fix (status-side, after the pf drop lands)

- Add a status check: `nc`/socket probe of `127.0.0.1:443` directly — that
  becomes the real ingress once nginx binds it; no pf rule to verify anymore.
- Keep an end-to-end canary: `https://git.cove` (DNS → 443 → nginx → forgejo)
  instead of port-8443-only.
- If the pf path were ever reinstated: verify `pfctl -s info` **enabled** state
  AND rule text; treat "rule present, pf disabled" as broken (bringup
  self-skips on rule-text presence alone).

## Notes

- Immediate break fixed 2026-09-19 23:15 ET: `sudo pfctl -E`; verified 443
  probe + `https://git.cove` HTTP 200 + `git push origin` success.
- Standing hazard (until the pf drop lands): Surfshark (or any WireGuard
  client) reconnect can disable pf again. If HTTPS pushes to git.cove time
  out, check `pfctl -s info` first.
- Related: Cove doc `~/.agents/agents-md-detail/cove.md` documents
  `0.0.0.0:443` nginx binding, but compose defaults `NGINX_HTTPS_PORT=8443`
  with pf doing the 443 translation — docs and compose disagree on which layer
  owns 443. The pf drop makes the doc true.