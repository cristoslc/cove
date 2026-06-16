# Per-Machine DNS Names in Cove

Cove's DNS model is anonymous: `git.cove` resolves to `127.0.0.1` on every machine. That's correct for local access — you're always talking to your own Cove. But it creates an identity problem for multi-machine setups. If you have a MacBook and a Linux desktop both running Cove, and you want to reach the MacBook's forge from the Linux desktop, `git.cove` on the Linux desktop resolves to `127.0.0.1` — the Linux desktop's own Cove, not the MacBook's.

The idea: give each Cove instance a unique, machine-scoped hostname. `git.cove.mbpbk` identifies the MacBook's forge. `git.cove.framework` identifies the Framework's forge. These names are unambiguous — they always mean a specific machine's Cove, regardless of where you're resolving from.

## The Model

Two DNS rules, layered by dnsmasq's most-specific-match semantics:

```
*.cove              → 127.0.0.1          (local — every machine resolves its own Cove)
*.cove.<machine>    → <machine-ip>       (remote — resolves to that specific machine)
```

dnsmasq matches the most specific `--address` rule. `git.cove` matches `/cove/` → `127.0.0.1`. `git.cove.mbpbk` matches `/cove.mbpbk/` (more specific) → the MacBook's IP. No split-horizon, no source-based routing, no new infrastructure. Just two address rules with different specificity.

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

### Local resolution (already works)

dnsmasq's `address=/cove/127.0.0.1` covers all `*.cove` names, including `git.cove.mbpbk`. On the MacBook, `git.cove.mbpbk` resolves to `127.0.0.1` — which is correct, because the MacBook is mbpbk.

### Remote resolution (the new part)

Each machine needs dnsmasq entries for the *other* machines it knows about. On the MacBook:

```
address=/cove/127.0.0.1
address=/cove.framework/100.64.0.6
address=/cove.pi/100.64.0.7
```

On the Framework:

```
address=/cove/127.0.0.1
address=/cove.mbpbk/100.64.0.5
address=/cove.pi/100.64.0.7
```

Most-specific-match handles the rest. `git.cove` → `127.0.0.1` (matches `/cove/`). `git.cove.framework` → `100.64.0.6` (matches `/cove.framework/`, more specific).

### Where do the remote entries live?

Two options:

**Option A: dnsmasq include directory (recommended)**

Same pattern as the nginx `user.d` directory from the DNS infrastructure musing. dnsmasq reads `/etc/dnsmasq.d/*.conf`. Cove renders `cove.conf` (the local wildcard). The user drops a `remote.conf` with per-machine entries:

```
# ~/Documents/cove-data/dnsmasq/remote.conf
address=/cove.framework/100.64.0.6
address=/cove.pi/100.64.0.7
```

dnsmasq picks it up automatically (it reads all `.conf` files in the directory). No template rendering, no Ansible variables, no `cove up` dependency. The user maintains it — same as `user.d` for nginx.

**Option B: host_vars (Ansible-managed)**

Each machine's `host_vars/<hostname>.yml` lists remote peers:

```yaml
cove_peers:
  - slug: framework
    ip: 100.64.0.6
  - slug: pi
    ip: 100.64.0.7
```

The dnsmasq template renders them. This is the "Cove way" — everything through Ansible. But it means updating host_vars and re-running `cove up` when IPs change. Overengineered for a list of 2-3 entries.

**Recommendation: Option A.** The include-directory pattern is already established (nginx `user.d`). It's consistent, simple, and doesn't require `cove up` for IP changes.

### dnsmasq config change

None needed for the mechanism — dnsmasq already reads all `.conf` files in `/etc/dnsmasq.d/`. The user just drops `remote.conf` in the data directory (which is already mounted). Cove could create an empty `remote.conf` as a placeholder during `cove up`, but that's polish.

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

## What This Actually Buys

1. **Remote resolution is trivial.** Two dnsmasq rules. No split-horizon, no `/etc/hosts` on remote machines, no service discovery protocol.

2. **Unambiguous references.** "The issue is on `git.cove.mbpbk`" means something specific. "The issue is on `git.cove`" is ambiguous across machines.

3. **Reduces Tailscale reliance.** You still need Tailscale (or Wireguard) for the VPN layer — the IPs in dnsmasq are Tailscale IPs. But the *naming* layer is independent of Tailscale. No more `taila90e7.ts.net` in configs or URLs. If you switch from Tailscale to plain Wireguard, only the IPs in `remote.conf` change — the `.cove` names stay the same.

4. **Phone access without Tailscale naming.** From a phone on the tailnet, `https://git.cove.pi/` reaches tier-2. The phone needs to resolve `git.cove.pi` — which means either using Tailscale MagicDNS (if it supports custom names) or pointing the phone at a DNS server that knows the `.cove` names. This is the remaining gap: phones don't run dnsmasq.

5. **Mental model.** `*.cove` = my machine. `*.cove.<slug>` = that machine. The suffix encodes machine identity; the prefix encodes service identity. Natural hierarchy.

## Phone Resolution (Remaining Gap)

Phones don't run dnsmasq. They use whatever DNS the network provides. For a phone to resolve `git.cove.pi`, one of these must be true:

- **Tailscale MagicDNS supports custom names.** If you can register `git.cove.pi` as a MagicDNS name pointing to the Pi's Tailscale IP, the phone resolves it automatically. Unclear if Tailscale supports this.
- **The phone uses a DNS server that knows `.cove` names.** If tier-2 runs a DNS server (could be dnsmasq on the Pi) and the phone is configured to use it, `*.cove.<machine>` resolves. This requires either DHCP DNS configuration (LAN) or Tailscale's `--accept-dns` flag pointing at the Pi.
- **The phone has a local DNS proxy.** iOS/Android don't make this easy. A VPN-based DNS proxy (like Tailscale's own DNS) is the practical answer.

For now, the phone uses the Tailscale FQDN (`mbpbk-202602.taila90e7.ts.net`) to reach specific machines. The per-machine `.cove` names work between Cove instances (laptop ↔ laptop, laptop ↔ tier-2) where dnsmasq is running. Phone support is a future problem.

## Recommendation

1. **Adopt the suffix naming convention:** `{service}.cove.{machine}`. Machine identity is a suffix after `.cove`, not a prefix before the service.

2. **Add `*.cove.{{ ansible_hostname }}` to the mkcert cert.** One wildcard per machine covers all its services for remote clients.

3. **Add regex server blocks to nginx** for per-machine routing:
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

4. **Use a dnsmasq include file for remote machine entries.** `~/Documents/cove-data/dnsmasq/remote.conf` with `address=/cove.<slug>/<ip>` lines. User-maintained, same pattern as nginx `user.d`.

5. **Don't build a Cove DNS sidecar.** Two dnsmasq rules per remote machine is not a service discovery problem. Revisit at 3+ machines if maintaining `remote.conf` becomes tedious.

6. **Phone resolution stays on Tailscale FQDN for now.** Per-machine `.cove` names work between Cove instances. Phone support needs Tailscale DNS integration — a separate problem.

## Open Questions

1. **Should the machine slug be the hostname or a user-chosen label?** Hostname (`mbpbk`) is automatic and unique. User-chosen label (`macbook`, `tier2`) is more readable. Hostname is the right default — it's already unique, already known to Ansible (`ansible_hostname`), and doesn't require configuration. But the slug in `remote.conf` is user-written anyway, so the user can choose whatever label they want. The cert wildcard uses `ansible_hostname`; the dnsmasq entry uses whatever slug the user picks. They should match, but dnsmasq doesn't care.

2. **Should `cove up` create a skeleton `remote.conf`?** A commented-out example file would teach the pattern. Low priority.

3. **What about the Tailscale FQDN server block?** It stays. The Tailscale FQDN is still the primary remote-access name for phones and non-Cove devices. Per-machine `.cove` names are for Cove-to-Cove communication.

4. **Does `*.cove` still need to be in the cert?** Yes — for local access (`git.cove`, `vault.cove`) and for `*.pages.cove`. The cert has both `*.cove` and `*.cove.{{ ansible_hostname }}`.

5. **What about `ca.cove` from the root cert distribution musing?** `ca.cove` is a local-only name (served by the local nginx). It doesn't need a per-machine variant — you always download the CA cert from the machine you're trying to trust. But `ca.cove.mbpbk` would work automatically if someone tried it (the regex catch-all or a dedicated block would serve it).
