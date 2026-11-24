# Naming and transport are two problems

*A musing on mDNS, p2p meshes, and whether Cove should change how `*.cove` names resolve. 2026-11-24. Not an ADR; nothing here is implemented.*

The question was whether to use mDNS for hostnames instead of standing up a resolver and editing hosts files everywhere, and whether something like NetBird or another local-first mesh VPN would do the job better. Separation first: one of those solves naming, the other solves reachability. Most of the confusion in this area comes from answering both with one tool.

## What Cove already does, measured

- `/etc/resolver/cove` and `/etc/resolver/cove.<hostname>` point every query for those suffixes at `127.0.0.1:5354`.
- `compose/dnsmasq/cove.conf.j2` answers with suffix rules: `address=/cove/127.0.0.1`, `address=/cove.local/127.0.0.1`, and `<hostname>` variants pointing at the tailnet address.
- `compose/nginx/default.conf.j2` serves 17 `server_name` entries, each in a `.cove` and a `.cove.local` form.
- A local CA issues wildcard certificates, so TLS does not care which of the two families a client uses.

Two things follow. There is no per-host editing to remove: `address=/cove/...` is a suffix match, which is a wildcard, so `git.cove`, `vault.cove`, `pages.cove` and every future name resolve without a new entry. What exists per machine is one resolver file, and on this Mac both forms resolve through `dscacheutil`, so the mechanism is not the bottleneck it was when hosts files were the method.

The remaining costs are smaller and different from "edit hosts everywhere": one file per machine, a second name family to keep in step, and a homegrown DNS container in the critical path.

## What mDNS would buy, and what it cannot do

mDNS gives zero-configuration naming on a LAN: a responder advertises a name, every Mac and every Avahi-equipped Linux box resolves it without a file. That is real, and it is why it is tempting.

It cannot carry Cove's shape:

- **No wildcards.** RFC 6762 defines multicast records, not a zone. Every name is advertised individually, so `git.cove.local`, `vault.cove.local`, `pages.cove.local` and the next twenty each need an advertisement. That is the same per-name toil as a hosts file, moved from a file into a process.
- **`.local` is reserved for mDNS.** A unicast resolver answering `.local` sits in a documented collision, and browsers special-case the suffix. Cove currently publishes a second family under `.cove.local`, which is exactly the collision, tolerated today because the resolver wins.
- **Containers cannot answer multicast through the bridge.** The services are behind nginx in Docker; an mDNS advertisement would have to come from a host process, which means a responder that reads the vhost list, which is a worse version of the DNS container that already exists.
- **No remote reach.** mDNS is link-local multicast. It does nothing for a laptop on a train.

So mDNS would replace one file per machine with one responder per host and an advertisement per name, and would put a second name family into a reserved suffix. It is a worse fit than what exists, unless the only goal is zero per-machine configuration, which has better answers: push the resolver file by management tooling, or hand the zone out over DHCP.

## What a mesh VPN buys, and what it does not

NetBird, Tailscale, ZeroTier and Nebula solve reachability: they give every device a stable address on a virtual network and carry the packets. Their DNS features, MagicDNS in Tailscale's case and NetBird's DNS management, resolve *peers*: `host-a` resolves to a mesh address. That is not the same as a wildcard zone.

Cove's services all live behind nginx on one host. A peer name gets a device to that host; the seventeen vhosts still need names, and a mesh will not invent them. The mesh can point split-DNS at Cove's resolver, which is the useful combination: the tunnel carries the packet, Cove's zone answers the name. That is complementary rather than a replacement, and it is what the `<hostname>` suffix rules in `dnsmasq` are already shaped for.

If the driver is "reach Cove from a laptop that is not on the LAN", the mesh is the right tool and the naming should not change at all. If the driver is "stop maintaining a resolver", a mesh adds a resolver configuration rather than removing one.

## The decision I would actually make

Three shape decisions, in the order they constrain each other:

1. **Retire `.cove.local`, or keep it deliberately.** It is a reserved suffix served by a unicast resolver, and every vhost carries it. Dropping it halves the server names and removes a documented collision. Keeping it costs nothing today but will confuse the first client that treats `.local` as multicast.
2. **Serve the zone beyond the host.** A split-horizon answer from the same dnsmasq, reachable by LAN clients, removes the per-machine file for every machine that can reach the host. That is the real fix for "editing hosts everywhere", and it is one config change rather than a new protocol.
3. **Add transport only when a client actually needs it.** The zrok tunnel already exists for exactly this. A mesh becomes worth it when several devices need mutual reachability rather than one host's names, and at that point its split-DNS points at the zone in step 2.

## What would make this a bad idea

Running mDNS because it sounds modern, alongside the resolver, would give two mechanisms answering the same question with different lifetimes and no single source of truth. Adding a mesh before a client needs one adds a daemon, a control plane, and an authentication surface to solve a problem the tunnel already solves. And exposing the zone to the LAN is a real change: it publishes the service inventory of the host to anything on the link, which is why it belongs behind a decision rather than a config edit.

## What I would measure first

- Whether any client actually depends on the `.local` form. If nothing does, deleting it is free and it is the cheapest change on this list.
- How many machines carry a resolver file today, and whether their management tooling can push one. If it can, the per-machine cost is already handled.
- Whether the tunnel already answers the remote-access need, which the zrok service suggests, before adding a mesh to the same job.
