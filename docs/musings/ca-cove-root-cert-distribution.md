# ca.cove — Root CA Certificate Distribution

Cove uses mkcert to generate locally-trusted TLS certificates for `*.cove`. The root CA is installed on the host via `mkcert -install` (macOS Keychain, Linux NSS/certutil). But when you access Cove from another device — phone via Tailscale, another laptop on the tailnet, a VM — that device doesn't trust the mkcert CA. You get TLS warnings. Currently the only way to fix this is to manually copy the `rootCA.pem` file from the host to the other device and install it.

`ca.cove` solves this: a dedicated subdomain that serves the root CA certificate for download and installation.

## The Idea

```
https://ca.cove/ → serves rootCA.pem with Content-Type: application/x-pem-file
```

From any device that can reach Cove (phone, VM, second laptop), you open `https://ca.cove/` in a browser, download the cert, and install it. On iOS: download → Settings → Profile Downloaded → Install. On macOS: double-click → Keychain → trust. On Linux: `sudo trust anchor rootCA.pem`.

## What Needs to Change

### 1. mkcert cert SAN list (`bringup.yml`)

Add `ca.cove` to the mkcert certificate SANs so the TLS cert covers the new subdomain:

```yaml
- name: Generate mkcert cert for *.cove
  ansible.builtin.command:
    argv:
      - mkcert
      - -key-file
      - "{{ cove_data_root }}/certs/cove.local-key.pem"
      - -cert-file
      - "{{ cove_data_root }}/certs/cove.local.pem"
      - cove
      - git.cove
      - vault.cove
      - hc.cove
      - ca.cove                    # ← NEW
      - "*.pages.cove"
      - localhost
      - 127.0.0.1
      - "::1"
```

### 2. `/etc/hosts` entry (`bringup.yml`)

```yaml
- name: Add *.cove hostnames to /etc/hosts
  become: true
  ansible.builtin.lineinfile:
    path: /etc/hosts
    regexp: '^127\.0\.0\.1\s+.*cove(\s|$)'
    line: "127.0.0.1 cove git.cove vault.cove hc.cove ca.cove"
```

### 3. Mount root CA into nginx (`docker-compose.yml`)

The mkcert CAROOT directory contains `rootCA.pem` (public cert) and `rootCA-key.pem` (private key). Only the public cert should be served. Mount just the `rootCA.pem` file:

```yaml
nginx:
  volumes:
    - ${MKCERT_CAROOT:-~/Library/Application Support/mkcert}/rootCA.pem:/certs/rootCA.pem:ro
```

The CAROOT path varies:
- macOS: `~/Library/Application Support/mkcert`
- Linux: `~/.local/share/mkcert`

The env var `MKCERT_CAROOT` should be set in `bringup.yml` by running `mkcert -CAROOT` and capturing the output. This avoids hardcoding a platform-specific path.

### 4. nginx server block (`default.conf.j2`)

```nginx
# ca.cove — root CA certificate download
server {
    listen 443 ssl;
    server_name ca.cove;

    ssl_certificate     /certs/cove.local.pem;
    ssl_certificate_key /certs/cove.local-key.pem;

    location / {
        alias /certs/rootCA.pem;
        add_header Content-Type application/x-pem-file;
        add_header Content-Disposition 'attachment; filename="cove-root-ca.pem"';
    }
}
```

`alias` (not `root`) because we're serving a single file at the root path. `Content-Disposition: attachment` triggers a download rather than inline display — important for mobile browsers where "open PEM file" isn't a native action.

### 5. CAROOT detection (`bringup.yml`)

```yaml
- name: Detect mkcert CAROOT path
  ansible.builtin.command: mkcert -CAROOT
  register: mkcert_caroot
  changed_when: false

- name: Set MKCERT_CAROOT env var
  ansible.builtin.set_fact:
    mkcert_caroot_path: "{{ mkcert_caroot.stdout }}"
```

Then render `MKCERT_CAROOT={{ mkcert_caroot_path }}` into `.env`.

## Security Considerations

### Private key exposure

`rootCA-key.pem` lives in the same CAROOT directory as `rootCA.pem`. The volume mount must be scoped to the single file, not the directory. Mounting the entire CAROOT directory would expose the CA private key to the nginx container — and if nginx were compromised, that key could sign arbitrary certs trusted by every device with the CA installed.

The mount `.../rootCA.pem:/certs/rootCA.pem:ro` (single file, read-only) is safe.

### Who can download it?

Anyone who can reach `https://ca.cove/`. On the host machine, that's localhost only (nginx binds `127.0.0.1:8443`). Over Tailscale, it's anyone on your tailnet. This is fine — the root CA cert is public by nature (it's what you install on devices to trust the CA). The private key stays on the host filesystem, never served.

### Remote device access

`ca.cove` resolves on the host machine via `/etc/hosts`. From remote devices (phone on Tailscale, another laptop), the hostname doesn't resolve — Tailscale MagicDNS only resolves the machine's Tailscale FQDN, not arbitrary `*.cove` names. Two approaches cover this:

**Approach A: Serve at a known path on the catch-all block**

Add a `/ca` location to the catch-all (default) server block that serves the root CA. From a phone: `https://<tailscale-fqdn>/ca` downloads the cert. Simple, no new subdomain, no DNS problem.

```nginx
# In the catch-all server block:
location = /ca {
    alias /certs/rootCA.pem;
    add_header Content-Type application/x-pem-file;
    add_header Content-Disposition 'attachment; filename="cove-root-ca.pem"';
}
```

**Approach B: `ca.cove` subdomain + Tailscale Serve**

Add `ca.cove` as a Tailscale Serve target. Requires Tailscale to be running and configured. Adds complexity to bringup.yml (another `tailscale serve` invocation). The "proper" RESTful answer — a dedicated subdomain for a dedicated service.

## Recommendation

**Both.** The `ca.cove` server block is the canonical interface for host-machine access. The `/ca` location on the catch-all is the pragmatic fallback for remote devices where `ca.cove` doesn't resolve. Two nginx locations, one file, zero additional infrastructure.

## Open Questions

1. **Should `ca.cove` also serve instructions?** A simple HTML page at `https://ca.cove/` with platform-specific install instructions (macOS: double-click → Keychain → trust, iOS: download → Settings → install profile, Linux: `sudo trust anchor`) would be more useful than a raw PEM download. But that's scope creep — the PEM file alone solves the problem. Instructions can live in docs.

2. **What about the Tailscale cert itself?** If someone connects via Tailscale FQDN, they already trust Tailscale's CA. But if they want to use `*.cove` hostnames from a remote device (by editing their own `/etc/hosts`), they need the mkcert root CA. The `/ca` path on the catch-all covers this.

3. **Should `cove up` copy rootCA.pem to the data directory?** Instead of mounting from CAROOT (which varies by OS), `bringup.yml` could copy `rootCA.pem` into `~/Documents/cove-data/certs/` during provisioning. This decouples nginx from the mkcert CAROOT path and keeps all served files under the data directory. But it means the cert could go stale if mkcert is reinstalled. mkcert root CAs have a 10-year validity, so staleness is unlikely.

## Implementation Priority

Low. This is a polish item. The current workflow (manual `scp` or AirDrop of the root CA) works. `ca.cove` removes friction for multi-device setups but doesn't unblock any core workflow. Build after health daemon and stateless config.
