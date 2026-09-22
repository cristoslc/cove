# Cove + Public Tunnels (bore / zrok / et al)

**Status:** Musing — direction chosen by operator (2026-09-21): managed public relay, exposed as a `cove` CLI command. Tailscale Funnel only if fully automatable. Not yet sashayed into a spec.

## Operator decision (2026-09-21)

> "yes, the managed public relay is the goal. tailscale funnel only works if it can be fully automated, I want this to work as a `cove` cli command"

So the shape is: **`cove tunnel <cmd>` wraps a managed public relay client**. The relay is a third-party enhancement (allowed by PURPOSE.md's enhancement clause); the *client* runs inside the harbor as a container making outbound-only connections — no inbound exposure, no VPS, no port-forwarding. Tailscale Funnel is demoted to a conditional path: only surfaced if it can be fully automated end-to-end, otherwise dropped.

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

## The real question: the public DNS identity (operator follow-up, 2026-09-21)

Operator's point: local TLS (mkcert / Cove CA) is irrelevant to *external* callers anyway — an OAuth provider hitting `auth.myapp` or a webhook sender doesn't trust a local CA and never will. What those services see is only the **public-facing appearance**: the hostname they're given and the certificate that terminates at the relay edge. So the design question collapses to: **what public DNS name does a share adopt, and who owns that domain?**

Three postures:

1. **Relay's shared domain (free tier):** `x7f3k.localhost.run`, `abc123.share.zrok.io`. Zero setup, but the identity is disposable and shared — fine for ad-hoc webhook debugging, bad for OAuth redirect URIs you want to pre-register (many providers pin exact redirect origins).
2. **Operator's own domain at the relay (the real answer):** relay edge terminates `*.tun.cristos.example` via wildcard DNS + wildcard cert (zrok self-host/hosted supports a custom DNS zone with Caddy + DNS-provider API token; localhost.run supports custom domains on paid tier). The share gets a *stable, ownable* public identity (`myapp.tun.example`), redirect URIs can be registered once, and the local `*.app.cove` name becomes just the internal alias. This is the posture that makes OAuth/webhook flows actually work, because the public name is consistent across sessions.
3. **Public name without a relay:** skip the tunnel for identity — point real DNS at the machine and terminate TLS locally. Rejected: needs a public IP; same wall as before.

So the refined design: `cove tunnel up --target git.cove --public myapp.tun.example` where `--public` requires a configured operator domain (from `cove creds`), and the free-tier shared domain is the fallback when none is configured. The local `*.app.cove` identity and the public identity are separate names bound at the tunnel client (it rewrites Host on the internal hop), which matches how the ingress already routes.

### The two-identity problem (operator follow-up, 2026-09-21)

Operator's catch: an app behind a tunnel now has two DNS identities — `myapp.app.cove` (local) and `myapp.tun.example` (public) — and apps are not built for that. Concretely painful for:

- **Absolute URLs the app generates:** OAuth redirect URIs, email links, CSRF/CORS origin checks, cookies scoped to a domain, OpenID `redirect_uri` allowlists. An app that computes its public base URL from the request `Host` header flips identity depending on who's asking — which is exactly what you *don't* get in production, where identity is stable.
- **HSTS/cookies:** `Secure` cookies set under the public name won't exist under the local name; login flows that work locally can break publicly and vice versa.

Options for making the app see one identity:

1. **Public-only for tunneled apps (lean in):** the tunnel *is* the app's identity while it's being tested. Don't give the app a `*.app.cove` name at all — dnsmasq resolves `myapp.tun.example` *locally* straight to the ingress (dnsmasq can answer for non-`.cove` names too), and nginx routes it to the app. Local visitors, CI, and the tunnel all use the same name; only resolution differs (local: dnsmasq → loopback ingress; public: real DNS → relay → tunnel client → ingress). **This makes the app's world single-identity and is the strongest answer.** The relay-edge TLS terminates the public path; the internal hop carries the same Host. What you give up: the name only works when the relay/client is up (same as any share), and you need to own the domain for stable naming.
2. **Proxy-Host discipline:** keep both names, but make the ingress rewrite `Host:` so the app always sees the *public* name (`proxy_set_header Host myapp.tun.example`) whether the visitor came locally or via tunnel. App stays single-identity; bookmarks/redirects emit the public name even on the sofa. Cost: ingress config per share, and the local name becomes a pure alias.
3. **Base-URL config:** the app is configured with one canonical base URL (12-factor style). Works only for apps that honor `BASE_URL`/`X-Forwarded-Host` cleanly; many don't, and it's per-app ceremony.

Cove's instinct was option 1 for ad-hoc dev apps, option 2 for stable-identity services — but the operator wants **one strategy**, and re-reading it: **option 2 subsumes option 1.** If the ingress always rewrites `Host:` to the public name, then the app has a single identity (`myapp.tun.example`) regardless of whether a local alias exists at all. Option 1 is just option 2 with the local alias dropped from dnsmasq — a naming detail, not a strategy.

**Single strategy adopted (operator, 2026-09-21): the ingress-host-rewrite rule.**

- The tunnel client binds a share: `public name ⇄ target service`.
- The ingress (or the tunnel client's local hop) always presents the **public name** as `Host:` to the target, whether the visitor arrived via relay or locally.
- dnsmasq answers the public name locally (→ loopback ingress) and the relay answers it publicly (→ tunnel client → ingress). One name, two resolutions, app sees a single identity always.
- Local-only apps without a share simply don't have a public name yet — they keep plain `*.cove` names and normal ingress routing. When a tunnel is added, the share *assigns* the public identity; there is exactly one identity rule everywhere: "the app's canonical name is the name the outside world uses."

## The tension with offline-first

Cove's rule: third-party services may *enhance*, never *be foundational*. A self-hosted tunnel server satisfies this (bore/frp/rathole/zrok all can self-host). The risk is different: **the relay is an attack surface pointed at the public internet**, and Cove's security posture today assumes no inbound exposure at all. Any tunnel feature must be default-off, and its docs must say: only run the relay when you intend to share.

A second tension the deeper look surfaced: **the relay needs a public IP**. Cove runs on a dev machine behind NAT — a relay *inside the harbor* is only reachable from the public internet if the host has port-forwarded upstream, which defeats the point. So the realistic shapes are: (a) relay on a cheap VPS (new host prerequisite, breaks self-contained), (b) relay at home with router port-forward (operator-specific, not Cove's job), or (c) **a managed public relay used as an enhancement** — e.g. bore.pub or a zrok.io-hosted instance — which is allowed under PURPOSE.md's "third-party services may enhance Cove" clause as long as Cove doesn't *require* them. Option (c) is the one that keeps the operator experience "just works" without Cove shipping public-IP infrastructure.

## Rough shape if pursued

Direction chosen: managed public relay + `cove tunnel` CLI command. Revised shape:

1. **Pick the managed relay.** Candidates by fit:
   - **bore.pub** (bore's free public instance): zero account, zero signup, `bore local 8000 --to bore.pub` → `bore.pub:<random-port>`. Plaintext TCP through the relay, random port URLs (not `https://`). Weakest fit for webhook work (webhooks need real HTTPS URLs; a bare TCP port usually fails TLS/SNI-based webhook delivery).
   - **localhost.run**: SSH-based, zero install — `ssh -R 80:localhost:3000 nokey@localhost.run` → real HTTPS URL, no account for the anonymous tier. Uses the host's ssh (violates "nothing runs on the host" only in the sense that ssh already exists — Cove isn't installing it). Free tier: random subdomains, no custom domains.
   - **zrok.io** (hosted zrok): full zrok client features (public + private shares, reserved subdomains on free tier), but requires account signup + token exchange. Richest and most "product-like" fit for a `cove tunnel` command.
   - **localhost.run / pinggy / localhost-run style SSH wrappers** can be wrapped without any new binary at all — `cove tunnel up` literally shells out to `ssh -R`. Zero new containers, zero account ceremony on the free tier.
2. **CLI surface.** `cove tunnel up [port]` (or `cove tunnel share`) starts the client, prints the public URL, keeps it alive; `cove tunnel ls`; `cove tunnel down`. Config (account/token, if any) from `cove creds`/1Password per ADR-017 conventions.
3. ~~Client in the harbor where possible~~ — **operator: container, not host ssh.** The tunnel client is a small sidecar container on the compose network. Outbound-only network; no published ports. This resolves the host-ssh question entirely: nothing shells out on the host. Note: the localhost.run SSH mode would need an ssh *client* inside the sidecar container (e.g. dropbear or openssh-client in a tiny image) — still a container, still outbound-only.
4. **Tunnel-to-ingress, not tunnel-to-host-port** (operator follow-up, 2026-09-21): set the app up locally with a `*.app.cove.local`-style address through nginx ingress, then tunnel to *that*, not to a raw host port. **This is the right shape.** The ingress already owns Host-based routing for every `*.cove` service (`default.conf.j2` server blocks) — tunneling to it means the public URL traverses the identical path a local visitor takes: same routing rules, same upstreams. The tunnel client container sits on the compose network and proxies `https://nginx` with the right `Host:` header out through the relay; `cove tunnel up --target git.cove` = "make the existing ingress route publicly reachable". TLS is simple: the public certificate is the *relay's* (localhost.run/zrok terminate real HTTPS at their edge); the ingress's self-signed `*.cove` cert only covers the relay→client→nginx hop, which never leaves the machine. The one thing to verify per relay: Host header preservation end-to-end (both candidates do this).
   - If the operator wants dedicated sandbox apps rather than existing services, a wildcard `*.app.cove` ingress route + dnsmasq entry gives each share a real local identity (`webhook-test-1.app.cove`) mapping 1:1 to its public URL — an ingress extension, worth doing regardless.
   - **Nested wildcards (`*.myapp.cove`)**: DNS is fine — dnsmasq's `address=/cove/` answer covers all subdomain levels, and the `/etc/resolver/cove` split routes them all to dnsmasq. TLS is the limit: wildcard certs match exactly one level, so the `*.cove` cert won't cover `x.myapp.cove`. Multi-level identities need extra SANs on the cove CA cert (regenerated per share) or per-app certs. Also note the public side is flat either way — relay subdomains are single-level (`myapp.tun.example.com`), so public↔local naming is always a flat 1:1 map; nesting only pays off if the app itself expects multi-level hostnames. For v1, flat `*.app.cove` with hyphenated names is simpler and probably enough.
5. **Naming.** Random URLs by default; reserved/stable subdomains as an opt-in upgrade once an account is configured.
6. **Forgejo public sharing** stays a separate explicit decision — the tunnel command is for ad-hoc app testing first.

### What "fully automated" means for Tailscale Funnel

Funnel requires: Tailscale up + logged in, `funnel` policy enabled in the tailnet ACL, HTTPS enabled on the node, and `tailscale funnel <port>` running persistently. If `cove tunnel up` can idempotently check/enable each of those via the Tailscale CLI/API and fall back cleanly when Tailscale isn't installed, it qualifies as an automated path; if any step needs the admin console, it's out.

## Open questions

- Is this a real need or a nice-to-have? (webhooks during local dev seem like the strongest actual use case)
- Which managed relay: localhost.run (zero-account SSH, real HTTPS URLs, weakest CLI control) vs zrok.io (richest, needs account) vs bore.pub (zero-account, but bare TCP ports, no HTTPS)? Leaning: **localhost.run first** (zero signup, real HTTPS, no new binary), zrok.io as the upgrade path if reserved subdomains/private shares are wanted.
- ~~SSH-based wrapper runs on the host, not in a container~~ — operator prefers a container. Confirmed shape below.
- For Forgejo: is a stable reserved share worth the account, or is ad-hoc-only fine for v1?
- ~~Self-hosted relay has no public IP~~ — resolved: operator chose the managed-relay path.
- ~~bore's TCP-only model vs frp's HTTP vhost model~~ — mooted by the managed-relay decision; both were self-hosted server questions.
- Does the relay port conflict with the `:443` port-collapse question in `cove-up-sudo-friction.md`? — only matters for self-hosted relays; moot for managed relays.
- Tailscale Funnel: automate-or-drop — needs a concrete check of whether `tailscale funnel` can be enabled/verified idempotently from the CLI without the admin console.

## See also

- [`cove-dns-architecture.md`](cove-dns-architecture.md) — how `*.cove` resolves; a public tunnel is the "beyond the tailnet" leg of that story.
- [`cove-up-sudo-friction.md`](cove-up-sudo-friction.md) — `:443` exposure question, same `0.0.0.0` tension.
- [`PURPOSE.md`](../../PURPOSE.md) — Self-Contained, Offline by Default, Single Developer.