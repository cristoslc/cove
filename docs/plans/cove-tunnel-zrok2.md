---
title: "cove tunnel — managed public relay via zrok2"
created: 2026-09-22
status: Draft (rework: service picker + Cove-managed share routes, 2026-09-22)
source: docs/musings/cove-public-tunnels-bore-zrok.md (2026-09-22 update)
---

# Plan: `cove tunnel` (zrok2)

Implement the optional tunnel profile wrapping **zrok2** (zrok.io hosted, free tier) as
`cove tunnel <cmd>`, per the musing's adopted shape: managed relay, tunnel-to-ingress,
sidecar client container, closed-by-default shares.

## Scope

In:

1. **`cove tunnel up [TARGET]`** — starts the tunnel sidecar on the compose network
   (outbound-only, no published ports). TARGET resolution (operator rework, 2026-09-22 —
   no silent default, Cove manages nginx):
   - Bare `cove tunnel up` → **interactive picker** of services discovered from
     Cove's nginx ingress config (`compose/nginx/default.conf[.j2]`): every
     proxied vhost becomes an entry shown as `service — target` (e.g.
     `git — https://git.cove.local`). Regex-only vhosts, redirects, and health
     endpoints are excluded. Non-TTY bare form fails loud listing services.
     Unknown shorthand fails loud listing valid names.
   - `cove tunnel up git` → service shorthand, resolved against the discovered
     inventory.
   - `cove tunnel up https://git.cove.local` → explicit URL power path.
   - `--public <name>` — reserve a stable name (`<name>.share.zrok.io`,
     4–32 lowercase alnum).
   - `--private` — private share mode; prints the share token for `zrok2 access private`.
   - **Cove renders nginx for every public share**: a server block for
     `<name>.share.zrok.io` is generated into
     `compose/nginx/cove-tunnel-shares.conf` (new include mounted into nginx,
     included from `default.conf.j2` after `user.d`), routed to the selected
     service's upstream with `Host: $host` (ingress-host-rewrite single-identity
     rule), nginx reloaded via `nginx -t` + `nginx -s reload` (previous file
     restored on rejection). State is `COVE_TUNNEL_SHARES` (comma-separated
     `share=service` pairs) in the compose `.env`; bringup seeds an empty
     include so the bind-mount is never a directory. `down` removes the route.
2. **`cove tunnel ls`** — list active shares (name, target, public URL/token, ephemeral/reserved).
3. **`cove tunnel down [NAME]`** — tear down a share (and release ephemeral names).
4. **Auth/account bootstrap** — account token from `cove creds` (1Password, ADR-017
   conventions; new `Zrok Account` item convention). First `up` runs `zrok2 enable`
   idempotently (state in a named volume). Missing token → loud error pointing at
   `cove creds` setup, never a silent anonymous fallback.
5. **Compose profile** — `tunnel` profile, default-off (like LiteLLM/runner). Sidecar
   image pinned by digest. Interstitial caveat documented: unverified free account shows
   an anti-phishing page on first visit per public share URL; verify account (card) to remove.
6. **Docs** — `docs/services/tunnel.md`: onboarding journey (myzrok.io signup →
   `cove creds` → `cove tunnel up`), zrok2 v2 naming conventions, private-share story,
   cost ladder, localhost.run fallback.

Out of scope:

- Self-hosted zrok/bore relays (documented fallback only).
- Custom domains (myzrok Pro) — reserved `*.share.zrok.io` names are free and enough for v1.
- Forgejo public-identity sharing (`ROOT_URL` override while active) — separate explicit
  decision per the musing; not built here.
- Tailscale Funnel automation.
- Raw-TCP/bore path.

## Design decisions (locked by the musing)

- **Relay = zrok.io hosted free tier.** Reserved names, private shares, token auth at $0.
  Interstitial page is the known cost of unverified free accounts.
- **Tunnel-to-ingress, not tunnel-to-host-port**: sidecar proxies to `https://nginx`
  with the right `Host:` header; public URL traverses the same path a local visitor takes.
- **Identity stays with the app** (`ROOT_URL` etc.) — the tunnel is a pipe. No `sub_filter`, ever.
- **Closed by default**: a share exists only while `cove tunnel up` for it is active
  (reserved names persist, shares don't auto-restart except via the agent with reserved
  names — v1 keeps it explicit).
- **Offline-first**: `cove up` and all core commands never require the tunnel or network;
  `cove tunnel up` without internet fails loudly, degrades nothing.
- **Binary is `zrok2`** (v2.0.0+); pin latest v2.x.

## Implementation sketch

- `cli/src/cove_cli/tunnel.py` — command group (`up/ls/down`), subprocess-wrapping the
  zrok2 binary inside the sidecar (`docker compose exec tunnel zrok2 ...`).
- `compose/tunnel.yml` (new compose resource): `zrok2` sidecar service, `profiles: [tunnel]`,
  bind-mounted state volume under the Cove data root (`~/Documents/cove/tunnel/`),
  env from `.env` (`ZROK_ACCOUNT_TOKEN`, `ZROK_SHARE_NAME` optional).
- `bringup.yml`: render tunnel env + optional reserved-name share declaration when the
  profile is active.
- Tests (per coverage matrix; mark `e2e`/`staging` where they hit the real relay):
  - unit: command parsing, name validation (lowercase alnum, 4–32 chars), env rendering
  - e2e (gated): `up → URL reachable → down → URL gone`; reserved-name persistence;
    private-share access flow; missing-token failure is loud.

## Test command

```
uv run --directory cli pytest -x -q -m "not e2e and not staging"
```

## Acceptance

1. `cove tunnel up` (TTY) → picker; selecting `git` → public HTTPS URL whose
   nginx route was rendered and reloaded by Cove; `cove tunnel down` removes it.
2. `cove tunnel up git` shorthand → same flow without the picker; unknown name
   fails loud listing valid services; bare form without TTY fails loud with the
   service list (no silent default target).
3. Private share reachable only via `zrok2 access private` from a second environment.
4. No tunnel profile → stack unchanged, zero zrok references in `docker ps`.
5. Non-e2e test suite green without network access.