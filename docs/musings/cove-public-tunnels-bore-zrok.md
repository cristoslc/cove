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

## Candidates

| Tool | Lang | Protocol | Server weight | Auth | Notes |
|------|------|----------|--------------|------|-------|
| **bore** | Rust | TCP only | tiny (<1k LOC, one binary) | shared secret | Minimal; no HTTP vhosts — each share = one port. Simplest to reason about. |
| **frp** | Go | TCP/UDP/HTTP vhosts | heavier, TOML config | token | Most featureful self-hosted option; vhost support means one relay port can host many HTTP shares by hostname — closest to "wildcard" model. |
| **rathole** | Rust | TCP/UDP | small, TOML | token | frp-like but lighter; no HTTP vhosts. |
| **zrok** | Go | HTTP/TCP (OpenZiti) | heavy — full OpenZiti stack | accounts/tokens | Richest model (public + private shares, ACLs), biggest dependency footprint; overkill for one operator. |
| **cloudflared** | Go | HTTP/TCP | none self-hosted (Cloudflare's edge) | CF account | Violates self-contained principle — Cloudflare as foundational infra. Rejected. |

## The tension with offline-first

Cove's rule: third-party services may *enhance*, never *be foundational*. A self-hosted tunnel server satisfies this (bore/frp/rathole/zrok all can self-host). The risk is different: **the relay is an attack surface pointed at the public internet**, and Cove's security posture today assumes no inbound exposure at all. Any tunnel feature must be default-off, and its docs must say: only run the relay when you intend to share.

## Rough shape if pursued

1. `compose/` gains a `tunnel/` profile with one relay service (probably **frp** if we want hostname-based shares on one port, **bore** if we want minimal TCP only).
2. `cove tunnel up` renders server config (ports, secret from `cove creds`), brings it up, prints the public URL(s).
3. `cove tunnel share <local_port> [--hostname x]` opens an ad-hoc share; `cove tunnel shares` lists active; `cove tunnel down` stops everything.
4. Forgejo public sharing stays manual: if the operator wants `git.cove` publicly reachable, they opt in explicitly and accept the exposure.
5. Optional enhancement later: Tailscale Funnel covers the same use case with zero new services — worth documenting as the "if you already run Tailscale" path before building anything.

## Open questions

- Is this a real need or a nice-to-have? (webhooks during local dev seem like the strongest actual use case)
- bore's TCP-only model vs frp's HTTP vhost model — which matches how Cove names things?
- Does the relay port conflict with the `:443` port-collapse question in `cove-up-sudo-friction.md`?
- zrok's OpenZiti footprint is appealing for *private* shares (share with one friend without exposing publicly) but is it worth the container weight?

## See also

- [`cove-dns-architecture.md`](cove-dns-architecture.md) — how `*.cove` resolves; a public tunnel is the "beyond the tailnet" leg of that story.
- [`cove-up-sudo-friction.md`](cove-up-sudo-friction.md) — `:443` exposure question, same `0.0.0.0` tension.
- [`PURPOSE.md`](../../PURPOSE.md) — Self-Contained, Offline by Default, Single Developer.