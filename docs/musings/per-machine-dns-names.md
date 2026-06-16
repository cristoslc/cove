# Per-Machine DNS Names in Cove

Cove's DNS model is anonymous: `git.cove` resolves to `127.0.0.1` on every machine. That's correct for local access — you're always talking to your own Cove. But it creates an identity problem for multi-machine setups. If you have a MacBook and a Linux desktop both running Cove, and you want to reach the MacBook's forge from the Linux desktop, `git.cove` on the Linux desktop resolves to `127.0.0.1` — the Linux desktop's own Cove, not the MacBook's.

The idea: give each Cove instance a unique, machine-scoped hostname. `git.cove.mbpbk` identifies the MacBook's forge. `git.cove.framework` identifies the Framework's forge. These names are unambiguous — they always mean a specific machine's Cove, regardless of where you're resolving from.

## The Model

Each tier-1 Cove machine publishes two DNS rules:

```
*.cove              → 127.0.0.1       (local — all services on this machine)
*.cove.<its-slug>   → <its-network-ip> (identity — this machine, reachable from elsewhere)
```

The first rule handles local access. The second rule publishes the machine's identity at its network address — the Tailscale IP (or LAN IP, or Wireguard IP). This is the answer remote machines need.

Remote machines don't maintain IP→slug mappings. They add the peer's dnsmasq as a DNS source for that peer's domain suffix. On macOS, a resolver file at `/etc/resolver/cove.<slug>`:

```
nameserver <peer-ip>
port 5353
```

When the local machine queries `git.cove.mbpbk`, the OS resolver sees the `cove.mbpbk` domain suffix, forwards the query to the MacBook's dnsmasq at `100.64.0.5:5353`, and gets back `100.64.0.5` — the MacBook's own answer about itself. Each machine is the authority for its own identity. Remote machines just need to know where to ask.

## Naming Convention

Suffix-based: `{service}.cove.{machine}`. Reads naturally: "the git service on cove, on machine mbpbk."

```
git.cove.mbpbk       → MacBook's forge
vault.cove.mbpbk     → MacBook's vault
git.cove.framework   → Framework's forge
git.cove.pi          → Tier-2's forge (always online)
```

From any machine:
- `git.cove` → that machine's own forge (local)
- `git.cove.mbpbk` → MacBook's forge (remote, resolves to MacBook's IP)
- `git.cove.pi` → tier-2's forge (remote, resolves to Pi's IP)

## DNS Implementation

### What each machine publishes (Cove-managed)

Every Cove instance renders two dnsmasq rules in `cove.conf`:

```
address=/cove/127.0.0.1
address=/cove.{{ ansible_hostname }}/{{ ts_ip }}
```

On the MacBook (`ansible_hostname=mbpbk`, Tailscale IP `100.64.0.5`):

```
address=/cove/127.0.0.1
address=/cove.mbpbk/100.64.0.5
```

On the Framework (`ansible_hostname=framework`, Tailscale IP `100.64.0.6`):

```
address=/cove/127.0.0.1
address=/cove.framework/100.64.0.6
```

The first rule handles all local access. The second rule publishes the machine's identity at its network address — `git.cove.mbpbk` resolves to `100.64.0.5` when queried against the MacBook's dnsmasq. Each machine is the authority for its own identity.

The Tailscale IP is available at provision time (`tailscale status --json` already runs in `bringup.yml`). If Tailscale isn't running, the second rule falls back to `127.0.0.1` (local-only mode).

### What remote machines add (user-managed)

To reach another Cove instance, add a resolver file pointing at that machine's dnsmasq. On macOS, `/etc/resolver/cove.<slug>`:

```
# /etc/resolver/cove.mbpbk
nameserver 100.64.0.5
port 5353
```

```
# /etc/resolver/cove.framework
nameserver 100.64.0.6
port 5353
```

```
# /etc/resolver/cove.pi
nameserver 100.64.0.7
port 5353
```

macOS's resolver sends queries for `*.cove.mbpbk` to `100.64.0.5:5353` (the MacBook's dnsmasq), which answers with `100.64.0.5`. Queries for `*.cove.framework` go to `100.64.0.6:5353` (the Framework's dnsmasq), which answers with `100.64.0.6`. Queries for bare `*.cove` stay local (`/etc/resolver/cove` → `127.0.0.1:5353`).

On Linux, the equivalent is `dnsmasq`'s `server=/cove.mbpbk/100.64.0.5#5353` directive (forward queries for that domain suffix to that server). Same pattern, different config syntax.

The resolver files are user-maintained — same pattern as nginx `user.d`. Add a peer, add a resolver file. No IP→slug mappings to maintain. Each machine knows its own IP; remote machines just need to know where to ask.

### Resolution flow

| Query | Resolver used | Queries | Answer |
|-------|--------------|---------|--------|
| `git.cove` | `/etc/resolver/cove` → `127.0.0.1:5353` | local dnsmasq | `127.0.0.1` |
| `git.cove.mbpbk` | `/etc/resolver/cove.mbpbk` → `100.64.0.5:5353` | MacBook's dnsmasq | `100.64.0.5` |
| `git.cove.framework` | `/etc/resolver/cove.framework` → `100.64.0.6:5353` | Framework's dnsmasq | `100.64.0.6` |
| `git.cove.pi` | `/etc/resolver/cove.pi` → `100.64.0.7:5353` | Pi's dnsmasq | `100.64.0.7` |

Each machine is the authority for its own identity. No overrides, no IP→slug mappings, no split-horizon. Just "ask the machine that owns that name."

## TLS

Each Cove's cert needs to cover `*.cove.<its-own-machine-slug>` for remote clients connecting to it. When the Framework connects to `git.cove.mbpbk`, it hits the MacBook's nginx — the MacBook's cert must be valid for that name.

mkcert supports multiple wildcards in one cert:

```yaml
- name: Generate mkcert cert for *.cove + per-machine wildcard
  ansible.builtin.command:
    argv:
      - mkcert
      - -key-file
      - "{{ cove_data_root }}/certs/cove.local-key.pem"
      - -cert-file
      - "{{ cove_data_root }}/certs/cove.local.pem"
      - "*.cove"
      - "*.cove.{{ ansible_hostname }}"          # ← per-machine wildcard
      - cove
      - git.cove
      - vault.cove
      - hc.cove
      - ca.cove
      - "*.pages.cove"
      - localhost
      - 127.0.0.1
      - "::1"
```

`*.cove.mbpbk` matches `git.cove.mbpbk`, `vault.cove.mbpbk`, `hc.cove.mbpbk` — any service on the mbpbk machine. One wildcard covers all services for that machine. Each Cove's cert includes its own machine's wildcard.

RFC 2818: `*.cove.mbpbk` is valid — the wildcard is the leftmost label, matching exactly one label. `git.cove.mbpbk` has `git` as the leftmost label, which `*` matches.

## nginx

Service-specific regex server blocks route per-machine names to the right backend. One block per service covers all machines:

```nginx
# Per-machine forge — git.cove.<slug> and cove.<slug>
server {
    listen 443 ssl;
    server_name ~^git\.cove\.[a-zA-Z0-9-]+$ ~^cove\.[a-zA-Z0-9-]+$;
    ssl_certificate     /certs/cove.local.pem;
    ssl_certificate_key /certs/cove.local-key.pem;
    location / {
        proxy_pass http://forgejo_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}

# Per-machine vault — vault.cove.<slug>
server {
    listen 443 ssl;
    server_name ~^vault\.cove\.[a-zA-Z0-9-]+$;
    ssl_certificate     /certs/cove.local.pem;
    ssl_certificate_key /certs/cove.local-key.pem;
    location / {
        proxy_pass http://vault_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

The existing non-regex blocks (`git.cove`, `vault.cove`) stay as-is for the local names. The regex blocks catch all per-machine variants.

## What This Buys

1. **Remote resolution is trivial.** One resolver file per peer. No IP→slug mappings, no overrides, no split-horizon. Each machine is the authority for its own identity.

2. **Unambiguous references.** "The issue is on `git.cove.mbpbk`" means something specific. "The issue is on `git.cove`" is ambiguous across machines.

3. **Reduces Tailscale reliance.** You still need Tailscale (or Wireguard) for the VPN layer — the resolver files point at Tailscale IPs. But the *naming* layer is independent of Tailscale. No more `taila90e7.ts.net` in configs or URLs. If you switch from Tailscale to plain Wireguard, only the IPs in resolver files change — the `.cove` names stay the same.

4. **Mental model.** `*.cove` = my machine. `*.cove.<slug>` = ask that machine. The suffix encodes machine identity; the prefix encodes service identity. Natural hierarchy.

5. **Self-describing.** Each machine publishes its own IP. When a machine's IP changes (new Tailscale node key, new network), it updates its own dnsmasq config. Remote machines don't need to track IP changes — they just keep forwarding to the same resolver file. The authoritative machine always knows its own address.

## Phone Resolution (Remaining Gap)

Phones don't run dnsmasq. They use whatever DNS the network provides. For a phone to resolve `git.cove.pi`, one of these must be true:

- **Tailscale MagicDNS supports custom names.** If you can register `git.cove.pi` as a MagicDNS name pointing to the Pi's Tailscale IP, the phone resolves it automatically. Unclear if Tailscale supports this.
- **The phone uses a DNS server that knows `.cove` names.** If tier-2 runs a DNS server (could be dnsmasq on the Pi) and the phone is configured to use it, `*.cove.<machine>` resolves. This requires either DHCP DNS configuration (LAN) or Tailscale's `--accept-dns` flag pointing at the Pi.
- **The phone has a local DNS proxy.** iOS/Android don't make this easy. A VPN-based DNS proxy (like Tailscale's own DNS) is the practical answer.

For now, the phone uses the Tailscale FQDN (`mbpbk-202602.taila90e7.ts.net`) to reach specific machines. The per-machine `.cove` names work between Cove instances (laptop ↔ laptop, laptop ↔ tier-2) where dnsmasq is running. Phone support is a future problem.

## Recommendation

1. **Adopt the suffix naming convention:** `{service}.cove.{machine}`. Machine identity is a suffix after `.cove`.

2. **Each machine publishes its own identity.** `cove.conf` renders `address=/cove.{{ ansible_hostname }}/{{ ts_ip }}` — the machine's own network address. The Tailscale IP comes from `tailscale status --json` (already available in `bringup.yml`).

3. **Remote machines add resolver files, not overrides.** `/etc/resolver/cove.<slug>` with `nameserver <peer-ip>` and `port 5353`. One file per peer. The OS forwards queries for that domain suffix to the authoritative machine's dnsmasq.

4. **Add `*.cove.{{ ansible_hostname }}` to the mkcert cert.** One wildcard per machine covers all its services for remote clients connecting to `git.cove.mbpbk` etc.

5. **Add regex server blocks to nginx** for per-machine routing:
   ```nginx
   server {
       listen 443 ssl;
       server_name ~^git\.cove\.[a-zA-Z0-9-]+$ ~^cove\.[a-zA-Z0-9-]+$;
       # proxy to forgejo
   }
   server {
       listen 443 ssl;
       server_name ~^vault\.cove\.[a-zA-Z0-9-]+$;
       # proxy to vault
   }
   ```

6. **Phone resolution stays on Tailscale FQDN for now.** Phones don't have `/etc/resolver/`. Per-machine `.cove` names work between Cove instances where resolver files can be configured.

## Open Questions

1. **Should the machine slug be the hostname or a user-chosen label?** Hostname (`mbpbk`) is automatic and unique. User-chosen label (`macbook`, `tier2`) is more readable. Hostname is the right default — it's already unique, already known to Ansible (`ansible_hostname`), and doesn't require configuration. But the slug in `remote.conf` is user-written anyway, so the user can choose whatever label they want. The cert wildcard uses `ansible_hostname`; the dnsmasq entry uses whatever slug the user picks. They should match, but dnsmasq doesn't care.

2. **Should `cove up` create a skeleton `remote.conf`?** A commented-out example file would teach the pattern. Low priority.

3. **What about the Tailscale FQDN server block?** It stays. The Tailscale FQDN is still the primary remote-access name for phones and non-Cove devices. Per-machine `.cove` names are for Cove-to-Cove communication.

4. **Does `*.cove` still need to be in the cert?** Yes — for local access (`git.cove`, `vault.cove`) and for `*.pages.cove`. The cert has both `*.cove` and `*.cove.{{ ansible_hostname }}`.

5. **What about `ca.cove` from the root cert distribution musing?** `ca.cove` is a local-only name (served by the local nginx). It doesn't need a per-machine variant — you always download the CA cert from the machine you're trying to trust. But `ca.cove.mbpbk` would work automatically if someone tried it (the regex catch-all or a dedicated block would serve it).
