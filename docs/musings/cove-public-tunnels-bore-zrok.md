# Cove + Public Tunnels (bore / zrok / et al)

**Status:** Musing — half-formed idea. Not ready for sashay.

## The question

What would it look like to incorporate bore, zrok, or a similar ngrok alternative into Cove — to make local apps accessible for testing over the public web, and optionally give Forgejo (or a single page) a public URL?

## Why it's tempting

Everything in Cove today is either loopback-only (`127.0.0.1:8443`), LAN-reachable, or tailnet-reachable. A tunnel closes the last gap: a webhook receiver at a real HTTPS URL, a demo page shared over coffee-shop WiFi, a friend clicking a Forgejo link without joining your tailnet. All of these are *enhancements* — Cove works fully without them.

## How it would fit Cove's architecture

- **Optional profile, like LiteLLM or the runner.** `cove tunnel up` starts the service; default stack untouched.
- **Server inside the harbor.** A tunnel *server* (relay) in a container fits the "nothing runs on the host" rule. The relay publishes one TCP/HTTPS port outward.
- **Two models:** `cove tunnel serve <port>` (ad-hoc: expose a local dev port, get a URL, throw it away) and a persistent share (e.g. `git.cove → git.example.com`, opt-in).
- **Auth:** bore supports a shared secret; zrok has account/token auth. Default should be *closed by default* — a share exists only when explicitly created, and each share gets an explicit allow/deny posture.
- **DNS/naming:** two options: (a) relay on a wildcard public domain you own, e.g. `*.tun.example.com` (requires a domain — new host prerequisite), or (b) random URLs like ngrok's `abc123.tunnel.example.com`. Option (b) needs zero per-share config, but option (a) composes with the dnsmasq wildcard story (`tunnel.cove` as the internal alias for the relay).

## Candidates (deeper look)

| Tool | Lang | Protocol | Server weight | Auth | Notes |
|------|------|----------|--------------|------|-------|
| **bore** | Rust | TCP only | tiny (~400 LOC, one binary) | HMAC challenge-response shared secret | Minimal; no HTTP vhosts — each share = one port. **Caveat: secret is auth, not encryption — traffic flows plaintext through the relay** (x-cmd guide). To get TLS you must front the relay with nginx/Caddy, which Cove already runs — so this is fixable, but it's real work. Control port 7835 + tunnel port range; narrow the range (`--min-port`/`--max-port`) to shrink the scanner-visible surface. |
| **frp** | Go | TCP/UDP/HTTP(S) vhosts | heavier, TOML config | token | vhostHTTPPort lets one relay port host many HTTP shares by hostname — closest to the wildcard model. **Security note: frp appears in MITRE ATT&CK (S1144) as a malware operator's tool — its ubiquity cuts both ways.** There's a real recent auth-bypass pattern: frp 0.43.0–0.68.0 had an HTTP vhost routing bypass via `routeByHTTPUser` (Vulners). Keep it pinned and watch releases. |
| **rathole** | Rust | TCP/UDP | small, TOML | token | frp-like but lighter; no HTTP vhosts. |
| **zrok** | Go | HTTP/TCP (OpenZiti) | heavy — OpenZiti controller + router + frontend + PostgreSQL, plus zrok2-init bootstrap (1–2 min) | accounts/tokens | Richest model (public + **private** shares). The private-share story is genuinely different: a friend installs the zrok CLI and reaches the share without a public URL at all. But the container weight is 4+ services; a lot for one operator. |
| **cloudflared** | Go | HTTP/TCP | none self-hosted (Cloudflare's edge) | CF account | Violates self-contained principle — Cloudflare as foundational infra. Rejected. |
| **ssh -R** | — | TCP | zero new containers (your existing VPS) | your existing SSH keys | The zero-install option: `ssh -R` to any VPS you own needs no new service at all. Weaknesses: needs a VPS (new host prerequisite), `GatewayPorts` config, no HTTP vhost routing natively, and keepalives/hangups need care. But: no third-party binary, no new attack surface beyond SSH itself. Worth naming because "do nothing, document ssh -R" is a legitimate Cove-shaped answer. |

### Key findings from the deeper look

1. **bore's plaintext-through-relay is the real differentiator, not its TCP-only model.** With Cove's existing nginx, TLS termination in front of the bore relay closes this — but then you're maintaining a custom stack (nginx → bore relay → local), not just dropping in a binary.
2. **frp's vhost model matches Cove's naming best** but frp is also the tool most abused by attackers (MITRE S1144) — meaning: (a) it's battle-tested, (b) it's on scanner/radar lists, (c) its auth layer has had real CVEs. Pinning + monitoring is required either way.
3. **zrok is the only candidate whose default model is "share with one person, privately"** — which is closer to Cove's single-developer worldview than "expose publicly". But it wants 4 containers, PostgreSQL, and a bootstrap init step. Too much for an optional profile today; revisit if private sharing becomes a real need.
4. **Tailscale Funnel already covers the "share with the public" case** for operators who run Tailscale — with zero new services. Documenting that path (in a docs page, not code) might be the honest v1.
5. **ssh -R to a personal VPS** is the zero-container option Cove docs can recommend with no new code. The gap it leaves: no ad-hoc URL management, no TLS termination story (you'd front it with the VPS's own nginx/Caddy), and it requires a VPS — which violates "Cove requires exactly three things from the host" *for the share feature only*, not for Cove itself.

## The tension with offline-first

Cove's rule: third-party services may *enhance*, never *be foundational*. A self-hosted tunnel server satisfies this (bore/frp/rathole/zrok all can self-host). The risk is different: **the relay is an attack surface pointed at the public internet**, and Cove's security posture today assumes no inbound exposure at all. Any tunnel feature must be default-off, and its docs must say: only run the relay when you intend to share.

A second tension the deeper look surfaced: **the relay needs a public IP**. Cove runs on a dev machine behind NAT — a relay *inside the harbor* is only reachable from the public internet if the host has port-forwarded upstream, which defeats the point. So the realistic shapes are: (a) relay on a cheap VPS (new host prerequisite, breaks self-contained), (b) relay at home with router port-forward (operator-specific, not Cove's job), or (c) **a managed public relay used as an enhancement** — e.g. bore.pub or a zrok.io-hosted instance — which is allowed under PURPOSE.md's "third-party services may enhance Cove" clause as long as Cove doesn't *require* them. Option (c) is the one that keeps the operator experience "just works" without Cove shipping public-IP infrastructure.

## Rough shape if pursued

1. `compose/` gains a `tunnel/` profile with one relay service (probably **frp** if we want hostname-based shares on one port, **bore** if we want minimal TCP only).
2. `cove tunnel up` renders server config (ports, secret from `cove creds`), brings it up, prints the public URL(s).
3. `cove tunnel share <local_port> [--hostname x]` opens an ad-hoc share; `cove tunnel shares` lists active; `cove tunnel down` stops everything.
4. Forgejo public sharing stays manual: if the operator wants `git.cove` publicly reachable, they opt in explicitly and accept the exposure.
5. Optional enhancement later: Tailscale Funnel covers the same use case with zero new services — worth documenting as the "if you already run Tailscale" path before building anything.

## Open questions

- Is this a real need or a nice-to-have? (webhooks during local dev seem like the strongest actual use case)
- **Self-hosted relay has no public IP** — the deeper look found the "relay in the harbor" idea mostly doesn't work without a VPS or port-forward. Is a docs-only recommendation (ssh -R / Tailscale Funnel / bore.pub as enhancement) actually the v1, with a first-class `cove tunnel` profile deferred until there's evidence of repeated need?
- bore's TCP-only model vs frp's HTTP vhost model — which matches how Cove names things?
- Does the relay port conflict with the `:443` port-collapse question in `cove-up-sudo-friction.md`?
- zrok's private-share model is the closest fit to Cove's single-developer worldview, but its container weight (4 services + Postgres) is out of proportion for an optional profile. Revisit when a concrete need shows up?

## See also

- [`cove-dns-architecture.md`](cove-dns-architecture.md) — how `*.cove` resolves; a public tunnel is the "beyond the tailnet" leg of that story.
- [`cove-up-sudo-friction.md`](cove-up-sudo-friction.md) — `:443` exposure question, same `0.0.0.0` tension.
- [`PURPOSE.md`](../../PURPOSE.md) — Self-Contained, Offline by Default, Single Developer.