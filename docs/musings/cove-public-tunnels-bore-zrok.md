# Cove + Public Tunnels (bore / zrok / et al)

**Status:** Musing — kept for reference. The original trigger (Forgejo not reachable by Kepler) was resolved as a **TLS configuration issue, not a tunneling need** (2026-09-21). The use case for public tunneling may resurface differently; the design thinking here remains worth keeping but is not active.

## Resolution (2026-09-21)

The motivating problem — "make Forgejo accessible to Kepler via gitkraken.dev" — turned out to be a TLS problem, not a reachability problem. No tunnel was needed. The musing is retained because the design exploration (managed relay, tunnel-to-ingress, Forgejo's ROOT_URL/SSH_DOMAIN knobs, two-instance analysis, ActivityPub federation assessment) is broadly useful if a public-tunneling need resurfaces with a different shape.

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

## Two Forgejo instances, one local + one tunneled, same machine (operator proposal, 2026-09-21)

Operator's refined idea: both Forgejo instances run on the local machine (no VPS). The local one is `git.cove` (offline-first, canonical). The second is a public-identity instance (`git.gitkraken.dev`) that's tunneled to the public web. Both point to the **same files on disk** — same repos — so there's one canonical repo, one set of data. The repo sees only one remote (the local one, preferably). ActivityPub federates the social layer (PRs, issues) between the two instances, if needed at all.

### Why this is elegant

- **No identity problem.** Each instance has its own `ROOT_URL` — local is `https://git.cove.local/`, public is `https://git.gitkraken.dev/`. No rewriting, no split-horizon, no `sub_filter`. Each instance is a clean, independent identity.
- **No VPS.** Both containers run in Cove's compose. The public one is tunneled via the managed relay (same tunnel mechanism as before). No second machine, no $4/mo.
- **One canonical repo on disk.** The operator's work happens against the local instance; Kepler's work arrives via the public one. Same git objects, same `~/Documents/` data root, same backups.
- **ActivityPub is optional**, not load-bearing. If PR/issue federation matures, the two instances federate the social layer. If not, they're just two views onto the same repos with different identities — still useful.

### The hard technical question: can two Forgejo instances share the same data directory?

**No. Not safely.** From Codeberg's clustered-Forgejo discussion (#259): even a single Forgejo instance has race conditions (e.g. authorized-keys rewrites). Two instances on the same data directory would:
- **Corrupt the SQLite database** — each instance has its own `app.ini`, its own DB, its own migration state. Two writers to the same SQLite file is data loss.
- **Fight over git config writes** — Forgejo writes remotes and config to repo `.git/config` at runtime; two instances racing on the same files is undefined behavior.
- **Desync notifications, cache, and search index** — each instance maintains its own; events fire only for the acting instance; the notification icon gets out of sync (confirmed by Codeberg cluster operators).
- **Migration safety** — during upgrades, all but one instance must be stopped, then upgraded, then restarted. Two instances complicating that is real operational risk.

Gitea Enterprise's HA docs confirm: multi-instance requires shared *POSIX* storage (NFS/Gluster) for `/data`, and even then it's an enterprise feature with caveats. On a single machine with bind mounts to `~/Documents/`, it's not supported.

### Can they share the *git repo directory* but not the *app data*?

Closer to viable. Forgejo's layout (`compose/docker-compose.yml:35-36`) separates app data (`/data/gitea` — DB, config, sessions) from repo storage (`/data/git` — bare repos). Two instances could:
- Each have their **own** `/data/gitea` (own SQLite DB, own config, own `ROOT_URL`).
- Share `/data/git` (the bare repos) — **read-only for one of them**, or with git's own file locking.

But this is fragile: Forgejo writes to repo `.git/config` (hooks, remotes, etc.), and two instances writing to the same bare repo's config concurrently is unsafe. Even read-only access for the second instance would break on any push (Forgejo updates repo metadata on push). **Two Forgejo instances cannot safely share the same bare repo directory.**

### What *would* work: git-level mirroring between two independent instances

The safe version of the two-instance model:
- **Instance A (local, `git.cove`):** full Forgejo, own data, own DB, canonical repos. Offline-first.
- **Instance B (public, `git.gitkraken.dev`):** full Forgejo, own data, own DB, **separate repo copies**. Tunneled to public web.
- **Sync:** post-receive mirror hook on A pushes to B's API/git endpoint; or B pulls from A on a schedule; or the operator pushes to both via dual remotes.

This is the two-instance model from the previous section, just co-located on one machine. It's safe but adds: a second Forgejo container, a second DB, mirror config, and sync lag. The repo on B is a clone, not the same objects — pushes from Kepler land on B and must mirror back to A.

### Honest assessment

| Approach | Safe? | One repo? | Identity clean? | Complexity |
|---|---|---|---|---|
| Shared data dir | **no** (corruption) | yes | yes | lowest but broken |
| Shared repo dir, separate app data | **no** (git config races) | yes | yes | medium but broken |
| Two instances + git mirroring | yes | no (two copies) | yes | highest (mirror config, sync lag) |
| **Single instance + tunnel** | **yes** | **yes** | **yes** (ROOT_URL = public) | **lowest working option** |

The single-instance + tunnel — where Forgejo's `ROOT_URL` is set to the public FQDN and dnsmasq resolves it locally too — is still the simplest *working* answer. One instance, one repo, one identity, one pipe. The two-instance model is architecturally appealing (each instance is a clean identity) but either unsafe (shared data) or adds mirroring ceremony (separate data). And ActivityPub PR federation isn't shipped, so the social-layer benefit isn't available today either.

**The operator's instinct — "one repo, the repo sees one remote" — is exactly right.** Only the single-instance + tunnel model delivers that. The two-instance model breaks "one repo" no matter how you slice it.

Operator's new idea: instead of tunneling to the local Forgejo, run **two Forgejo instances** — local (Cove, `*.cove`, offline-first) + public (cheap VPS, real domain, always-on) — federated via ActivityPub. Kepler talks to the public one. PRs and issues federate. Cheaper than GitLab (512MB VPS feasible).

### What this buys

- **No tunnel at all.** The public Forgejo is natively reachable. Kepler clones/pushes to it directly over real DNS + real TLS.
- **Local-first preserved for the primary instance.** Cove's Forgejo stays local, offline, in `~/Documents/`, works on a plane.
- **ActivityPub federates the social layer** — issues, PRs (as ForgeFed objects), reviews, comments — so work done on either side propagates to the other. If a Kepler-driven PR lands on the public instance, the operator sees it on the local one (and vice versa).
- **RAM:** a public Forgejo on a $4/mo 512MB-1GB VPS is feasible. GitLab needs 4GB+.

### The catch — git data doesn't federate

**ActivityPub/ForgeFed federates issues, PRs, reviews, stars. It does NOT federate the git repositories themselves.** So:
- Kepler pushes a commit to the public Forgejo's repo. That repo is a *separate git repository* on the VPS — not the same object store as Cove's local Forgejo.
- The two instances each have their own copy of the repo. They're independent clones that share history, not mirrors.
- To keep them in sync: `git remote add` both and push to each, or a post-receive mirror hook on one side, or manual pull. That's ceremony — the same ceremony whether or not ActivityPub is in the picture. ActivityPub doesn't remove it.

### Forgejo federation maturity — not there yet (verified 2026-09-21)

From the search: Forgejo's federation is **actively in progress but incomplete**. What works today: user activity following (PR #4767 — follow a user, see their activity as AP Notes). What's being worked on: following issues from Mastodon. The Forgejo FAQ explicitly warns: *"The Forgejo project reserves the right to make breaking changes to its federation components with no prior warning. Such changes may result in the (sub-)domain used for your Forgejo instance to be 'burned'."* ForgeFed (the AP extension for forge federation) is "not finished yet" per the ForgeFed site and community discussions. PR federation specifically — the operator's exact use case — is **not yet a shipped feature**. Issue federation is closer but still in progress.

So: the two-instance + AP architecture is the right *direction* for a federated future, but **it's not buildable today for the PR/issue use case**. Building on it now would mean running two Forgejo instances and manually syncing repos (git-level) while waiting for AP to mature for the social layer.

### Honest decomposition

- **ActivityPub solves the "Kepler files a PR/issue and the operator sees it locally" problem** — once PR/issue federation ships. Not today.
- **ActivityPub does NOT solve the "Kepler clones the repo and pushes commits" problem** — that always requires either the public instance being canonical (Cove's becomes a clone/mirror) or git-level mirroring between the two.
- **The two-instance model shifts where the canonical repo lives.** If Kepler pushes to the public one, the public one is canonical for Kepler-facing work. Cove's local one is a satellite. That's a real shift from "Cove is the harbor, everything is local" — the harbor now has an outpost. Whether that's acceptable depends on whether the operator's primary work happens locally (Cove canonical, public is read-only mirror for Kepler) or on the public side (public canonical, Cove is a clone).

### Comparison: tunnel vs two-instance

| | Tunnel (single Forgejo) | Two-instance + AP |
|---|---|---|
| Reachability for Kepler | tunnel pipe to local Forgejo | public Forgejo, native |
| Canonical repo | Cove (local, offline-first) | public instance (or split) |
| Git sync needed | no (one repo) | yes (two repos must mirror) |
| PR/issue sync | no (one instance) | AP federation — not ready today |
| VPS cost | none (managed relay) | $4/mo VPS |
| Complexity | tunnel client container + relay | second Forgejo + AP config + git mirroring |
| Local-first | fully preserved | preserved for local instance; canonical may shift |
| Works today | yes | no (AP PR federation not shipped) |

### Conclusion

The two-instance + AP model is the right long-term architecture for a federated multi-forge world, and it's worth watching. But for the concrete need today (Kepler reaches Forgejo for PRs), **the tunnel is the simpler, working-now answer**: one Forgejo, one repo, one canonical identity, one pipe. The two-instance model adds a VPS, a second Forgejo, git mirroring, and depends on an unfinished federation protocol — more moving parts to solve the same reachability problem.

If the operator's real goal is "Kepler files PRs that I review locally without a tunnel," that's a federated future worth pursuing — but it's a bigger project than the tunnel, and it's gated on Forgejo shipping PR federation. File as a separate musing / future direction, not a v1 tunnel replacement.

Short answer: **neither.** Both were considered as potential escape hatches from the tunnel identity problem. Neither avoids the fundamental reachability requirement.

**ActivityPub (Forgejo federation):** Forgejo federation is real and in progress, but it doesn't solve the core use case. Kepler needs `git clone` / `git push` — git protocol over HTTP/SSH, not ActivityPub. ActivityPub federates social metadata (stars, issues, PRs as objects), not git data transfer. Worse: ActivityPub federation is server-to-server HTTP, so federating instances must be *publicly reachable to federate at all* — it adds a public-exposure requirement rather than removing one. Orthogonal to the tunnel: helps with event propagation, doesn't help with git operations. File under "interesting future feature, not a tunnel replacement."

**GitLab self-hosted:** Heavier (4GB+ RAM, PostgreSQL + Redis + Sidekiq vs Forgejo's <512MB SQLite). More mature remote-access features (built-in Pages with custom domains, built-in registry) — but doesn't solve reachability. You still need it publicly reachable for Kepler to clone/push. Would break Cove's minimalism principles (SQLite, single-binary, opinionated simplicity) without removing the tunnel need. The tunnel problem is identical on GitLab.

**The real insight from considering both:** a publicly-reachable git instance is inherently a public service. There's no protocol swap or platform swap that avoids exposing it. The "native" solution is a VPS-hosted Forgejo with real public DNS — but that breaks local-first (the forge isn't local anymore, doesn't work on a plane, data leaves `~/Documents/`). The tunnel is the compromise that keeps the forge local while making it reachable, and Forgejo is already one of the most tunnel-friendly apps available (three config knobs: `ROOT_URL`, `DOMAIN`, `SSH_DOMAIN`). Neither ActivityPub nor GitLab changes that tradeoff.

**What this confirms about the tunnel design:** the tunnel solves *reachability*, and reachability is the actual problem. Identity is solved by Forgejo's own config (not the tunnel, not DNS tricks, not body rewriting). The tunnel is a pipe; the app is its own identity authority. This is the simplest possible division of responsibility, and both alternative approaches considered here would have added complexity without removing the need for a pipe.

Operator's question: "does forgejo have a reverse proxy or tunnel-friendly configuration?" Yes — Forgejo is explicitly designed for reverse-proxy deployment, and it has the exact knobs this use case needs. From the Forgejo docs and verified against Cove's current compose:

**The three knobs that matter for a tunnel share:**

1. **`ROOT_URL`** (`FORGEJO__server__ROOT_URL`, currently `https://git.cove.local/` in Cove). The canonical public URL Forgejo stamps on every link it generates — PR URLs, clone URLs, OAuth callbacks, email links. Set this to `https://git.gitkraken.dev/` and every link Forgejo emits works for Kepler and GitKraken, period. This is the single most important setting; it's the app's whole identity.
2. **`DOMAIN`** (`FORGEJO__server__DOMAIN`, currently `git.cove.local`). The server's domain for display and internal routing. Usually matches `ROOT_URL`'s host. Set to `git.gitkraken.dev`.
3. **`SSH_DOMAIN`** (`FORGEJO__server__SSH_DOMAIN`, currently `git.cove.local`, `compose/docker-compose.yml:14`). **This is the key insight: Forgejo separates HTTP identity from SSH identity.** Clone URLs show `git@git.cove.local:org/repo` for SSH and `https://git.cove.local/org/repo` for HTTP. You can set `ROOT_URL=https://git.gitkraken.dev/` (HTTP goes through the tunnel) while keeping `SSH_DOMAIN=git.cove.local` (SSH stays local-only via tailnet) — or set `SSH_DOMAIN` to a separate public host if SSH needs to be public too. **For Kepler, HTTP through the tunnel is probably enough; SSH can stay on the tailnet.**

**What this means for the tunnel design:**

- Forgejo doesn't need body rewriting, Host-header tricks, or split-horizon DNS to work behind a tunnel. It needs **three config values set correctly** — `ROOT_URL`, `DOMAIN`, `SSH_DOMAIN` — and a reverse proxy (nginx) forwarding to it with standard headers (`Host`, `X-Forwarded-Proto`). That's it. Forgejo is one of the most tunnel-friendly apps you could pick.
- The "messy use case" is actually clean: `cove tunnel` for Forgejo = set `ROOT_URL`/`DOMAIN` to the public FQDN + ensure nginx routes the public name to Forgejo + start the persistent tunnel. The config is IaC (compose env, rendered by bringup), not runtime hacks.
- **The split-horizon DNS is still useful but not load-bearing for Forgejo's correctness.** Forgejo with `ROOT_URL=https://git.gitkraken.dev/` works for public visitors regardless of what local DNS does. Split-horizon (dnsmasq answering `git.gitkraken.dev` locally → ingress) is a *local convenience* so the operator's browser uses the same name; without it, the operator just uses `git.cove` locally and `git.gitkraken.dev` remotely, and Forgejo doesn't care because it reads `ROOT_URL`, not the incoming Host.

**The real question this surfaces: does Forgejo even need the tunnel to think about identity at all?** Almost no. The tunnel's job is purely *reachability* — pipe public traffic to nginx → Forgejo. Forgejo handles its own identity via `ROOT_URL`. The tunnel client doesn't rewrite Host, doesn't do split-horizon, doesn't manage identity. It just carries bytes. The identity lives in Forgejo's config, set once, stable forever. This is much simpler than the whole identity chapter assumed.

> "ah, but B is the issue — we want to make forgejo accessible to kepler via gitkraken.dev"

Use case B isn't a hypothetical edge case. **It's the primary goal.** The concrete target: Forgejo reachable at a stable public URL on `gitkraken.dev` so that Kepler (an external system, not on the tailnet) can clone from and push to it on demand. That means:

- Real identity: `git.gitkraken.dev` (or similar), stable, real TLS, real public DNS.
- `ROOT_URL` must be the public URL — Forgejo emits PR/clone/clone-SSH links that Kepler and GitKraken follow; they have to resolve publicly.
- The tunnel must be **persistently up**, not ad-hoc — Kepler needs Forgejo reachable on demand, not "when the operator feels like sharing."
- Local-first still holds for everything *else*: Cove's own services (vault, litellm, pages) and dev apps stay `*.cove`, offline-first, untouched.

So the design has **two tiers**, not one strategy forced on everything:

1. **Stable public shares for designated services (the Forgejo/Kepler case).** A configured, persistent tunnel with a real owned-domain FQDN, split-horizon DNS (dnsmasq answers `git.gitkraken.dev` locally → ingress; real DNS → relay → tunnel client → ingress), `ROOT_URL` set to the public FQDN permanently. This is use case B, done right, for the specific services that need it. It requires the operator's domain + a persistent relay relationship — accepted cost for a persistent public Forgejo.
2. **Ad-hoc disposable shares for dev apps (the webhook-testing case).** `cove tunnel up <port>` → random public URL, pipe bytes, throw away. No identity ceremony. Use case A, unchanged.

The two tiers share the same tunnel client container and relay; they differ in persistence and identity. Tier 1 is configured in compose/bringup (IaC — the Forgejo share is declared, not ad-hoc). Tier 2 is CLI-driven and ephemeral.

**What this resolves from the identity chapter:** the split-horizon-on-owned-domain approach was right — it was just wrongly proposed for *all* apps. It's right for Forgejo-as-public-service, and wrong for everything else. Local-first holds for the everything-else; Forgejo gets a real public identity because it genuinely needs one. The `sub_filter` prohibition stands. The "two-identity problem" doesn't apply to Forgejo because it has one identity — the public one — and dnsmasq makes it resolve locally too.

Stepping back: the two-identity rabbit hole came from conflating two use cases with very different identity needs.

**Use case A — webhook testing during local dev.** Stripe/GitHub/Twilio POST to whatever URL you paste into their dashboard. They don't click the app's emitted links, don't follow its redirects, don't care about `ROOT_URL`. They need exactly one thing: a publicly reachable HTTPS URL that delivers their POST to a local receiver. The app stays `myapp.cove`, the webhook sender hits `abc123.localhost.run`, the tunnel pipes bytes. **No identity problem exists here at all.** The app doesn't even know it has a public name. This is the use case that originally motivated the musing, and it's trivial.

**Use case B — interactive browsing of an app that emits self-referential links** (Forgejo PR links, OAuth-provider flows, anything where a human clicks around on the tunneled app). Here the app's own link generation (`ROOT_URL`, absolute URLs, cookie domains) matters, and the two-identity friction is real. This is the use case the whole identity chapter was trying to solve — and it's the *harder, less common* one.

The smell the operator caught: **we've been redesigning Cove's naming to serve use case B, when use case A is the actual motivator and needs none of it.** Use case A works with the simplest possible tunnel — random public URL, pipe bytes to a local port, done. No canonical identity, no ROOT_URL, no split-horizon, no public domain prerequisite. The app keeps `*.cove`, the tunnel is a disposable pipe, everybody's happy.

**Reframed strategy: build for use case A first. Use case B is a known limitation, not a design driver.**

- `cove tunnel up <port>` → starts a managed-relay client container, prints a public HTTPS URL, pipes traffic to the local port (or to the ingress at `*.cove`). Zero identity ceremony. This covers webhook testing, ad-hoc demos, "show a friend this page for ten minutes."
- Use case B (stable public identity for Forgejo-style apps with self-referential links) is documented as **not supported by the tunnel** — or, much later, as a separate explicit feature with its own design (likely the ROOTURL-override-while-active path). It is not the thing we build first, and it does not get to reshape Cove's local-first naming.
- Everything in the identity chapter above (split-horizon, two-identity, ROOTURL-as-strategy, public-TLD-from-day-one) is **out of scope for v1**. Kept in the musing as a record of the thinking, but none of it gates the tunnel feature.

This restores the original framing: the tunnel is an enhancement for the common, easy case. The hard case stays hard and is explicitly deferred.

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

### Operator correction: same name inside and out — public TLD, split-horizon DNS (2026-09-21)

The ROOT_URL-config approach still leaves the URLs bad: apps emit `git.tun.example` and local visitors get a name dnsmasq doesn't answer, or the identity flips between contexts. The operator's real answer: **the internal and public names must be the same name.** That kills local-only domains for tunneled apps entirely — and points at two mechanisms:

1. **Public TLD from day one (the clean version).** Apps under test live on the operator's real public domain *always* — `myapp.example.com` — never on a `*.cove` alias. dnsmasq answers `myapp.example.com` locally (→ loopback ingress) while real public DNS answers it at the relay edge. Same FQDN, split-horizon resolution, the app sees one identity in every context, ROOT_URL is stable forever, no share/unshare identity churn. The `*.cove` namespace stays internal-only for Cove's own services (git.cove, vault.cove) — or they too get public names when shared, per the same rule.
   - Cost: requires owning a public domain and a wildcard record → new prerequisite, but one the operator already accepted for stable shares.
   - This *is* "one address, everywhere" from PURPOSE.md, finally realized fully: the FQDN doesn't change between local and public; only resolution does.
2. **Local DNS adopts the public bridge FQDN on activation (the fallback version).** When a share activates, dnsmasq gains an entry for the public FQDN (`git.tun.example` → ingress). Local callers then use the same name the public world uses. Weaker: the name exists locally only while the share is up; identities churn between sessions; and free-tier relay names (random subdomains) make this unusable. Only works with a stable operator domain — at which point option 1 dominates it (option 2 without option 1's "always" property adds complexity for nothing).

**Conclusion — revised twice after the operator caught a foundational error (2026-09-21):**

The split-horizon "public TLD from day one" strategy was wrong. It solves the tunnel's identity problem by breaking Cove's foundation: making apps depend on a public domain and external DNS from day one, just so an *optional* enhancement has clean identity. That inverts PURPOSE.md — "Offline by Default. The internet is optional. Network access is an enhancement, not a prerequisite." Forcing public-TLD identity on apps that may never be shared makes the enhancement load-bearing. The operator named this directly: "this is throwing out all of cove's local-first philosophy in order to accommodate public bridges that are optional."

**Corrected strategy: `*.cove` is primary, always; the tunnel maps it to a public identity as an enhancement.**

- Apps live on `*.cove` from day one, local-first, offline-works. This is the foundation and it doesn't move.
- A tunnel share *maps* a local identity to a public one: `cove tunnel up --target git.cove --public git.example.com`. The public name is an enhancement-layer alias, not the app's canonical identity.
- **The two-identity cost is the inherent price of opting into public exposure.** Apps that get shared publicly will emit some links under their local name (Forgejo's `ROOT_URL=https://git.cove.local/`) that don't resolve for public visitors. That's a real friction, and it's *acceptable* — because the alternative (forcing every app onto a public domain from day one) breaks every app that's never shared, which is most of them.
- Mitigations, in order of preference, all enhancement-layer only:
  1. For apps with a config knob (Forgejo `ROOT_URL`): allow the share to override it to the public FQDN *while the share is active*, restored on `cove tunnel down`. The app emits public links during the share; local links otherwise. Identity churns per-share, accepted.
  2. For apps without a knob: accept that public visitors may see local-name links, or don't tunnel that app for OAuth/PR-link flows. The tunnel is best for webhook debugging and ad-hoc demos, not for Forgejo PR sharing — and that's fine.
  3. `sub_filter` body rewriting: still prohibited. Still a trap.
- The free-tier shared-subdomain fallback (random `abc123.localhost.run`) stays for zero-prerequisite ad-hoc use. No operator domain required for v1.

This keeps the foundation intact: local-first wins, the tunnel is opt-in enhancement, and the identity friction is the honest cost of that opt-in rather than a reason to redesign Cove's naming. The earlier "split-horizon public TLD from day one" and "ROOT_URL-config as strategy" sections are both superseded by this. The `sub_filter` prohibition stands.

### The ROOT_URL problem (kept for the record — subsumed by the split-horizon strategy)

Operator's follow-up: apps like Forgejo don't trust the request `Host` for their generated links — they carry their own canonical identity in config. Cove already sets `FORGEJO__server__ROOT_URL` (default `https://git.cove.local/`, see `compose/docker-compose.yml:9` and `bringup.yml`). Every PR link, clone URL, and OAuth callback Forgejo emits is built from `ROOT_URL`, not from the incoming Host. So with only a Host rewrite:

- Visit via the tunnel → `Host: git.tun.example`, but Forgejo still stamps `https://git.cove.local/...` on every link it renders. A friend clicking a PR link gets an address that doesn't resolve outside the tailnet. **Reverse problem of what we feared: links leak the local name into the public world** — the mirror image of `sub_filter`/reverse-rewrite concerns.

So the honest answer to "do we need reverse-rewrite?":

- **Rewriting rendered links in responses (sub_filter-style reverse-rewrite) is a trap.** It breaks on compressed bodies, absolute redirects, JSON payloads, and signed content. Never solve identity by rewriting HTML in flight.
- **What Forgejo-class apps actually need is a config-level canonical base URL** — and Forgejo has exactly one knob: `ROOT_URL`. This is the app-level ceremony the single-identity rule must absorb.

**Refined single strategy — canonical identity is a share property, applied as config:**

1. The share is the source of truth for an app's canonical name: `cove tunnel up --target git.cove --public git.tun.example` sets the *identity*, and Cove renders it into the app's own config (`FORGEJO__server__ROOT_URL=https://git.tun.example/`) — not into nginx, not by rewriting traffic. Apps get their canonical name the same way they get any config: from the compose env / bringup render. IaC discipline holds.
2. The ingress Host rewrite stays, but it's now downstream plumbing: it makes local visitors *reach* the app under its canonical name; the app itself emits links from its configured ROOT_URL. Both layers agree because both are set from the same share definition.
3. Apps without a `ROOT_URL`-style knob that trust `Host`/`X-Forwarded-*` (most small dev servers) need nothing — the existing `proxy_set_header Host $host` behavior suffices. The strategy is: **config-driven canonical URL when the app has a knob, Host-rewrite when it doesn't** — decided per app by whether a knob exists, never by rewriting bodies.
4. For Forgejo specifically: `ROOT_URL` becomes `${FORGEJO_ROOT_URL:-https://git.cove.local/}` (already is), and the tunnel share for Forgejo overrides it via the compose `.env` — a one-line bringup change, consistent with how `cove creds` injects everything else.

This also answers the reverse-rewrite question fully: no `sub_filter`, ever. The name lives in (a) DNS at both edges, (b) the ingress Host header, (c) the app's own canonical-URL config — three places, one source of truth (the share), zero body rewriting.

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