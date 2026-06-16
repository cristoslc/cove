# Per-Machine DNS Names in Cove

Cove's DNS model is anonymous: `git.cove` resolves to `127.0.0.1` on every machine. That's correct for local access — you're always talking to your own Cove. But it creates an identity problem for multi-machine setups. If you have a MacBook and a Linux desktop both running Cove, and you want to reach the MacBook's forge from the Linux desktop, `git.cove` on the Linux desktop resolves to `127.0.0.1` — the Linux desktop's own Cove, not the MacBook's.

The idea: give each Cove instance a unique, machine-scoped hostname. `git.cove.mbpbk.` (or `mbpbk.git.cove`) identifies the MacBook's forge. `git.cove.framework.` identifies the Framework laptop's forge. These names are unambiguous — they always mean a specific machine's Cove, regardless of where you're resolving from.

## The Naming Convention

Two options for the subdomain structure:

**Option 1: Machine prefix before service**
```
mbpbk.git.cove     → MacBook's forge
mbpbk.vault.cove   → MacBook's vault
framework.git.cove → Framework's forge
```

**Option 2: Machine suffix after `.cove`**
```
git.cove.mbpbk     → MacBook's forge
vault.cove.mbpbk   → MacBook's vault
git.cove.framework → Framework's forge
```

Option 1 (`mbpbk.git.cove`) is better. It keeps `.cove` as the TLD-like suffix, puts the machine identifier in a consistent position (leftmost subdomain), and reads naturally: "the git service on cove, on mbpbk." It also means the wildcard cert (`*.cove`) still covers these names — `mbpbk.git.cove` is a subdomain of `cove`, which `*.cove` matches. Option 2 (`git.cove.mbpbk`) would need `*.*.cove` which mkcert wildcards don't support (they're single-level).

## Local Resolution (Already Works)

dnsmasq's `address=/cove/127.0.0.1` is a domain wildcard, not a subdomain wildcard. It matches any name ending in `.cove`:

```
dig mbpbk.git.cove @127.0.0.1 -p 5353       → 127.0.0.1  ✓
dig framework.vault.cove @127.0.0.1 -p 5353  → 127.0.0.1  ✓
dig anything.machine.cove @127.0.0.1 -p 5353 → 127.0.0.1  ✓
```

No config change needed. The wildcard already covers arbitrary-depth subdomains. On the local machine, `mbpbk.git.cove` resolves to `127.0.0.1` just like `git.cove` does. This is correct — from the MacBook, you want `mbpbk.git.cove` to reach the MacBook's own forge.

## Remote Resolution (The Hard Part)

From another machine, `mbpbk.git.cove` needs to resolve to the MacBook's IP, not `127.0.0.1`. This is the fundamental DNS problem: how does a name resolve differently depending on who's asking?

### Approach 1: Tailscale (Current, Works)

Tailscale MagicDNS already gives each machine a unique name (`mbpbk-202602.taila90e7.ts.net`). Tailscale Serve forwards HTTPS to Cove's nginx. From a phone: `https://mbpbk-202602.taila90e7.ts.net/` reaches the MacBook's forge.

The per-machine `.cove` name is cosmetic — `mbpbk.git.cove` is a nicer name than `mbpbk-202602.taila90e7.ts.net`, but it doesn't change the resolution mechanism. You'd still need Tailscale (or something like it) to route traffic to the right machine.

**What you could do:** Configure Tailscale Serve to also respond on `mbpbk.git.cove` (if MagicDNS supports custom names), or add a CNAME from `mbpbk.git.cove` to the Tailscale FQDN in a DNS server both machines use. But this adds Tailscale-specific configuration for a naming preference.

### Approach 2: mDNS / Bonjour (LAN Only)

On a local network, mDNS resolves `.local` names. `mbpbk.local` already resolves to the MacBook's LAN IP. You could configure the MacBook to advertise `mbpbk.git.cove` via mDNS, but mDNS only advertises the hostname, not arbitrary subdomains. And mDNS is LAN-only — doesn't work over the internet or from a phone on cellular.

### Approach 3: Split-Horizon DNS (Complex)

Run a DNS server that returns different answers based on the query source. From the MacBook, `mbpbk.git.cove` → `127.0.0.1`. From the Linux desktop, `mbpbk.git.cove` → MacBook's Tailscale IP. This requires a shared DNS server that both machines use, which knows the topology. Overengineered for two machines.

### Approach 4: /etc/hosts on Each Remote Machine (Manual, Works)

On the Linux desktop:
```
# /etc/hosts
100.64.0.5  mbpbk.git.cove mbpbk.vault.cove   # MacBook's Tailscale IP
```

On the MacBook:
```
# /etc/hosts
100.64.0.6  framework.git.cove framework.vault.cove  # Linux desktop's Tailscale IP
```

This works. It's manual. It requires knowing the other machine's Tailscale IP (which is stable). It's exactly what Cove already does for its own hostnames on the local machine. The pattern is consistent.

### Approach 5: A "Cove DNS" Sidecar (Future)

A lightweight DNS server that Cove instances use to discover each other. Each Cove announces its machine name and Tailscale IP. Other Cove instances query this to resolve per-machine names. This is a service discovery protocol, not just DNS. Overengineered for the current scale but could be the right answer at 3+ machines.

## What This Actually Buys

The per-machine naming convention is valuable even without solving remote resolution:

1. **Unambiguous references.** "The issue is on `mbpbk.git.cove`" means something specific. "The issue is on `git.cove`" is ambiguous across machines.

2. **Documentation and config clarity.** CI configs, webhook URLs, and documentation can use machine-scoped names. `GITEA_SERVER_URL=https://mbpbk.git.cove` is self-documenting.

3. **Future-proofing.** When multi-machine sync arrives (multi-stage-cove.md), per-machine names are necessary. You need to know which machine authored which change.

4. **Mental model.** The operator thinks in terms of machines ("my MacBook's forge", "the Linux desktop's vault"). The DNS should reflect that mental model.

## Relationship to Tier-2

In the multi-stage model, tier-2 is an always-online machine (Raspberry Pi, old laptop, desktop). It has a stable Tailscale IP. Per-machine names make tier-2's role explicit:

```
pi.git.cove     → tier-2's forge (always online, sync hub)
mbpbk.git.cove  → MacBook's forge (local, may be offline)
```

From a phone, you always connect to `pi.git.cove` — the tier-2 that's always up. From the MacBook, `pi.git.cove` resolves to the Pi's Tailscale IP (via `/etc/hosts` or Tailscale MagicDNS). The naming makes the topology visible.

## What Changes in Cove

### dnsmasq: Nothing

`address=/cove/127.0.0.1` already covers `mbpbk.git.cove` and any other per-machine name. No change needed.

### nginx: Server blocks need per-machine names

If you want `https://mbpbk.git.cove/` to work (not just resolve), nginx needs a server block for it. Options:

**A) Add per-machine server blocks to the template.** The `default.conf.j2` template already has `{{ ts_dns_name }}` for the Tailscale FQDN. Add `{{ machine_name }}.git.cove` similarly. This requires the machine name to be known at provision time (it is — hostname is a fact).

**B) Use the catch-all.** `server_name _` already catches unknown hostnames and proxies to Forgejo. `mbpbk.git.cove` would hit the catch-all and work. But it wouldn't get a dedicated server block with specific routing.

**C) Regex server block.** `server_name ~^(?<machine>[a-zA-Z0-9-]+)\.git\.cove$` routes any machine-prefixed git.cove to Forgejo. Same for vault: `~^(?<machine>[a-zA-Z0-9-]+)\.vault\.cove$`. This is the cleanest — one regex block covers all machines.

### /etc/hosts: Add per-machine entries for remote machines

This is manual and per-machine. Not something Cove automates (yet). But the pattern is documented.

### TLS: Already covered

`*.cove` wildcard cert covers `mbpbk.git.cove` (single-level wildcard matches `mbpbk.git.cove` because the wildcard is at the leftmost label). No cert change needed.

Wait — actually, `*.cove` matches `git.cove` and `mbpbk.cove` but does NOT match `mbpbk.git.cove`. RFC 2818: `*.cove` matches exactly one label. `mbpbk.git.cove` has two labels before `.cove`. So `*.cove` does NOT cover `mbpbk.git.cove`.

This is a real constraint. Options:
1. Use `*.*.cove` in the mkcert cert — but mkcert (and most TLS libraries) don't support multi-level wildcards.
2. Use a flat naming convention: `mbpbk-git.cove` instead of `mbpbk.git.cove`. Single label, covered by `*.cove`.
3. Add explicit SANs for known machine+service combinations: `mbpbk.git.cove`, `framework.git.cove`, etc. Requires regenerating the cert when machines change.
4. Accept that per-machine names won't have valid TLS from remote devices, and use the Tailscale FQDN (which has its own valid cert) for remote access.

**Option 2 (flat naming) is the pragmatic answer.** `mbpbk-git.cove` is a single label before `.cove`, covered by `*.cove`. It's less elegant than `mbpbk.git.cove` but works with the TLS constraint. The hyphen convention is clear: `{machine}-{service}.cove`.

```
mbpbk-git.cove       → MacBook's forge
mbpbk-vault.cove     → MacBook's vault
framework-git.cove   → Framework's forge
pi-git.cove          → Tier-2's forge
```

## Recommendation

1. **Adopt the flat naming convention:** `{machine}-{service}.cove`. Works with `*.cove` wildcard TLS. No cert changes needed.

2. **Add regex server blocks to nginx** for the major services:
   ```nginx
   # Per-machine git.cove
   server {
       listen 443 ssl;
       server_name ~^(?<machine>[a-zA-Z0-9-]+)-git\.cove$;
       ssl_certificate     /certs/cove.local.pem;
       ssl_certificate_key /certs/cove.local-key.pem;
       location / {
           proxy_pass http://forgejo_backend;
           # ...
       }
   }
   ```
   Same pattern for vault: `~^(?<machine>[a-zA-Z0-9-]+)-vault\.cove$`.

3. **Document the `/etc/hosts` pattern for remote machines.** On the Linux desktop, add the MacBook's Tailscale IP with per-machine names. This is the same pattern Cove uses for its own hostnames — consistent and understandable.

4. **Don't build a Cove DNS sidecar yet.** Two machines don't justify a service discovery protocol. Revisit at 3+ machines.

5. **Per-machine names reduce Tailscale reliance indirectly.** They don't replace Tailscale's VPN/routing layer. But they make the naming layer independent of Tailscale's naming (no more `taila90e7.ts.net` in configs). If you switch from Tailscale to plain Wireguard later, the `.cove` names stay the same — only the IPs in `/etc/hosts` change.

## Open Questions

1. **Should the machine name be the hostname or a user-chosen label?** Hostname (`mbpbk`) is automatic and unique. User-chosen label (`macbook`, `tier2`) is more readable. Hostname is the right default — it's already unique, already known to Ansible (`ansible_hostname`), and doesn't require configuration.

2. **Should `cove up` render per-machine server blocks automatically?** The machine name is available as `ansible_hostname`. The regex server blocks cover all machines generically — no per-machine rendering needed. One regex block serves all machines.

3. **What about the Tailscale FQDN server block?** It stays. The Tailscale FQDN is still the primary remote-access name (it has its own valid TLS cert from Tailscale). Per-machine `.cove` names are for local use and for `/etc/hosts`-based remote access between Cove instances.

4. **Does this conflict with the `user.d` include directory from the DNS infrastructure musing?** No. The regex server blocks are for Cove's own services (forge, vault). The `user.d` directory is for user-defined services. They're complementary — Cove provides machine-scoped names for its services, users provide names for theirs.
