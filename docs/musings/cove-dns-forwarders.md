# Cove DNS Forwarders — the SERVFAIL vs. gateway-override tension

**Status:** Musing — half-formed. Not ready for sashay.
**Related:** [`cove-dns-architecture.md`](cove-dns-architecture.md) (the architecture this sits on), [`dns-foundation.md`](../../docs/plans/dns-foundation.md) (the plan).

## The observation

`cove.conf.j2` is deliberately minimal:

```
address=/cove/127.0.0.1
address=/cove.local/127.0.0.1
address=/cove.{{ ansible_hostname }}/{{ ts_ip }}
address=/cove.local.{{ ansible_hostname }}/{{ ts_ip }}
bind-interfaces
listen-address=0.0.0.0
port=5353
no-hosts
no-resolv
```

`no-resolv` + **no `server=` forwarders** means dnsmasq is authoritative for `*.cove` and *nothing else*. Any non-`.cove` query → `SERVFAIL`. That's a deliberate posture: dnsmasq never leaks queries, never touches the network's DNS, never overrides anything. It is a pure, self-contained answerer for the Cove namespace.

The tension: **the moment any device routes *all* its DNS at dnsmasq, SERVFAIL becomes the answer for the whole internet.** That's what the original bug report described — a machine whose system-wide DNS pointed at `127.0.0.1`, so every non-`.cove` lookup died, and captive-portal resolution on hotel WiFi broke completely.

## The tempting fix, and why it's wrong

The obvious patch is to add upstream forwarders:

```
server=8.8.8.8
server=1.1.1.1
```

Now dnsmasq can resolve everything. But this **overrides the network's own DNS** — and the network's DNS is often the *desirable* one:

- **The gateway resolver knows local names.** On a home or office network, the DHCP-assigned resolver (often the router, e.g. `172.20.1.1`) is the only thing that resolves `printer.local`, `router.home`, internal hostnames, split-horizon zones. Hardcoding `8.8.8.8` bypasses it — those names silently stop resolving.
- **Captive portals.** On hotel/airport WiFi, `8.8.8.8` is unreachable until you pass the portal. Pointing dnsmasq at it makes the portal *worse*, not better — the portal needs the network's own DNS interception to work.
- **Privacy.** All DNS now goes to Google/Cloudflare, even for the dev machine's own lookups.
- **It's a lie about the network.** The whole point of DHCP DNS is "the network tells you who to ask." Hardcoding a public resolver says "I know better than your network" — and for local names, you don't.

So the forwarder question is a **false binary**: SERVFAIL-everything vs. override-the-gateway. Both are bad when dnsmasq is the system-wide resolver.

## The reframe: the forwarder question is a symptom of client-side routing

The real question isn't "what should dnsmasq forward to?" — it's **"should dnsmasq ever see a non-`.cove` query at all?"**

If the client uses a **scoped resolver** (macOS `/etc/resolver/cove` → `127.0.0.1:5353`), then dnsmasq *only ever receives `*.cove` queries*. It never needs a forwarder. `no-resolv` + no `server=` is then **correct and safe** — there is no SERVFAIL-everything, and there is no gateway override. The network's DNS stays untouched, the gateway keeps resolving local names, captive portals work.

This is the current state of the repo: `macos.j2` already writes scoped `/etc/resolver/cove.{{ hostname }}` files pointing at `{{ ts_ip }}:5353`, and this machine's `scutil --dns` shows only the hotel resolver (`172.20.1.1`) — no `127.0.0.1` in the system-wide list. So the original "system-wide DNS set to 127.0.0.1" bug report appears **stale or misdiagnosed** against the current tree. The scoped-resolver design already avoids the whole class of problem.

## Where forwarders genuinely matter: devices without scoped resolvers

The scoped-resolver answer only works on platforms that support per-domain resolvers. The honest matrix from the architecture musing:

- **macOS** — `/etc/resolver/` ✓ (scoped, no forwarder needed)
- **Linux** — systemd-resolved / resolv.conf ✓ (scoped, no forwarder needed)
- **Windows** — hosts file only ✗ (no per-domain resolver)
- **iOS / Android** — no `/etc/resolver` equivalent ✗ (Private DNS / DoH / Tailscale only)

For the ✗ platforms, the *only* way to reach `*.cove` is to point the whole device at dnsmasq — and then you're back in the false binary. For those, the least-bad answer is **forward to the network's DHCP-assigned DNS, not a hardcoded public resolver**:

- dnsmasq should learn the host's upstream DNS at runtime (the gateway / DHCP resolver), not bake in `8.8.8.8`.
- Mechanism: pass the host's DNS into the container (compose env from the host's `scutil --dns` / `resolv.conf`), or use `resolv-file` pointed at a host-synced resolv.conf, or a `server=` line templated from the detected gateway.
- This preserves local-name resolution and captive-portal behavior on the ✗ platforms, while still answering `*.cove`.

But this is complexity for a minority path. The ✗ platforms are also the ones where Tailscale (enhancement, not foundation) already solves it via Split DNS / MagicDNS.

## The design principle crystallizing

> **dnsmasq should never be a general-purpose resolver. It is an authoritative answerer for the Cove namespace. If a client can't scope its queries to `*.cove`, the fix is client-side routing (or a network-aware forwarder), not a hardcoded public upstream.**

Adding `server=8.8.8.8` to `cove.conf.j2` is the wrong move — it would override the gateway's desirable local forwarders and break captive portals and internal names on every platform, including the ones that currently work fine via scoped resolvers.

## Open questions

1. **Is the original bug report still valid?** The current `macos.j2` uses scoped resolvers and this machine's system DNS is clean. Was the `127.0.0.1` system-wide entry from an *older* script version, or a manual `networksetup`? Worth confirming before filing an issue — the fix may already be in place.

2. **Do we need a network-aware forwarder at all?** Only for the ✗ platforms (Windows/iOS/Android) without Tailscale. Is that path worth the complexity, or is "use Tailscale / manual IP" the honest answer?

3. **Should dnsmasq learn the host's upstream DNS?** If we ever do add forwarding, it must be the DHCP-assigned resolver (gateway), discovered at runtime — never a hardcoded public IP. Is there a clean way to pass the host's DNS into the container?

4. **Local vs. remote resolver target.** `macos.j2` points at `{{ ts_ip }}:5353`; the dev machine's own `/etc/resolver/cove` uses `127.0.0.1`. Should the template distinguish local (loopback) from remote (ts_ip)? The bare `cove`/`cove.local` vs. per-hostname resolver files also overlap — worth reconciling.

## See also

- [`cove-dns-architecture.md`](cove-dns-architecture.md) — the dnsmasq-as-foundation architecture, client routing matrix, iOS/Windows gaps.
- [`dns-foundation.md`](../../docs/plans/dns-foundation.md) — the plan that shipped scoped resolvers.
- [`cove-up-sudo-friction.md`](cove-up-sudo-friction.md) — the `0.0.0.0` exposure question, same shape as the `:5353` publish.
