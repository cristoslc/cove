# /config/* — Machine Configuration Endpoints

When you add a second device to your Cove setup — another laptop, a phone, a VM — you need the root CA cert from an existing machine so TLS works. You also need to know the machine's identity (its slug) and how to configure DNS so `*.cove.<slug>` names resolve.

`/config/*` paths on existing nginx server blocks serve these artifacts. No new subdomain, no new server block, no new SANs. You hit these before DNS is wired up — via Tailscale FQDN, direct IP, or `git.cove` on the host machine.

## The Endpoints

### `/config/ca` — Root CA Certificate

The mkcert root CA public cert as a PEM file download. Install this on any device that needs to trust `*.cove` TLS certificates from this machine.

```
GET https://git.cove/config/ca
→ Content-Type: application/x-pem-file
→ Content-Disposition: attachment; filename="cove-root-ca.pem"
```

On iOS: Safari downloads it → Settings → Profile Downloaded → Install. On macOS: double-click → Keychain → mark as trusted. On Linux: `sudo trust anchor cove-root-ca.pem`.

From a phone on Tailscale: `https://<tailscale-fqdn>/config/ca` (hits the catch-all, which has the same location). Use `curl -kO` from a terminal if the cert isn't trusted yet — that's what you're fixing.

### `/config/` — Machine Info Page

A human-readable HTML page. No JSON. Shows what a person needs to know and do:

```html
<!DOCTYPE html>
<html>
<head><title>Cove — mbpbk</title></head>
<body>
  <h1>Cove on mbpbk</h1>

  <h2>Trust this machine</h2>
  <p><a href="/config/ca">Download root CA certificate</a></p>
  <p>Install it in your system trust store. On iOS: open in Safari,
     go to Settings → Profile Downloaded → Install. On macOS:
     double-click → Keychain → mark as trusted.</p>

  <h2>Reach this machine</h2>
  <p>Once DNS is configured, these names resolve to this machine:</p>
  <ul>
    <li><code>git.cove.mbpbk</code> — forge</li>
    <li><code>vault.cove.mbpbk</code> — vault</li>
  </ul>

  <h2>Configure DNS (desktop OSes)</h2>
  <p>To resolve <code>*.cove.mbpbk</code> names, add a resolver
     pointing at this machine's DNS server:</p>

  <h3>macOS</h3>
  <pre># Create /etc/resolver/cove.mbpbk:
nameserver 100.64.0.5
port 5353</pre>

  <h3>Linux (dnsmasq)</h3>
  <pre># Add to /etc/dnsmasq.d/cove-mbpbk.conf:
server=/cove.mbpbk/100.64.0.5#5353</pre>

  <p>DNS IP: <code>100.64.0.5</code> (Tailscale)</p>
</body>
</html>
```

The page is rendered from a Jinja2 template (`config.html.j2`) with `{{ ansible_hostname }}` and `{{ ts_ip }}` substituted at provision time. The DNS config section is for desktop OSes — phones can't configure resolver files, so they use the Tailscale FQDN directly.

## nginx Implementation

Two `location` directives added to the existing `git.cove` server block and the catch-all (default) server block.

### git.cove server block

```nginx
server {
    listen 443 ssl;
    server_name git.cove cove;

    ssl_certificate     /certs/cove.local.pem;
    ssl_certificate_key /certs/cove.local-key.pem;

    location = /config/ca {
        alias /certs/rootCA.pem;
        add_header Content-Type application/x-pem-file;
        add_header Content-Disposition 'attachment; filename="cove-root-ca.pem"';
    }

    location = /config/ {
        alias /etc/nginx/config.html;
        add_header Content-Type text/html;
    }

    location / {
        proxy_pass http://forgejo_backend;
        # ...
    }
}
```

### Catch-all server block (remote-device access)

Same two locations. From a phone on Tailscale: `https://<tailscale-fqdn>/config/` shows the page, `https://<tailscale-fqdn>/config/ca` downloads the cert.

### Config HTML template (`config.html.j2`)

A static HTML file rendered at provision time. Stored alongside the nginx config template, rendered to `~/Documents/cove-data/nginx/config.html`, mounted into the nginx container.

## No New Subdomains, No New SANs

`/config/*` paths live on existing server blocks. No `config.cove` subdomain to add to mkcert SANs. No new TLS concerns. The paths work on any hostname that reaches nginx — `git.cove` (host machine), Tailscale FQDN (phone), direct IP (VM).

## What This Replaces

The `ca.cove` subdomain from the earlier root-cert-distribution musing is absorbed into `/config/ca`. The standalone `ca.cove` server block and its SAN entry become unnecessary.

## Configuration Flow

### Phone

1. Open `https://<tailscale-fqdn>/config/` in Safari (accept the TLS warning — you're about to fix it).
2. Tap "Download root CA certificate" → install via Settings → Profile Downloaded.
3. Bookmark the page. Now you know this machine is `mbpbk`, reachable at `git.cove.mbpbk` (once DNS is set up on your laptops).
4. Use `https://<tailscale-fqdn>/` for Forgejo access from the phone. The phone doesn't configure DNS — it uses the Tailscale FQDN directly.

### New Laptop

1. `curl -kO https://<tailscale-fqdn>/config/ca` → install in keychain.
2. Open `https://<tailscale-fqdn>/config/` → copy the DNS resolver snippet for your OS.
3. Create the resolver file. `dig git.cove.mbpbk` now resolves.
4. Repeat for each peer machine.

## Open Questions

1. **Should the HTML page also list peer machines?** If the machine knows about other Coves (from `remote.conf` or host_vars), it could list them. But that's scope creep — the page is about *this* machine's identity, not the topology.

2. **Should `cove up` print the config URL?** After bringup: "Config: https://git.cove/config/". Low effort, high discoverability.

3. **Does `/config/` conflict with any Forgejo routes?** Forgejo doesn't use a `/config/` path. The exact-match locations take priority over the `location /` proxy. No conflict.

4. **What about the Tailscale IP when Tailscale is down?** If Tailscale isn't running, `ts_ip` is unavailable. The DNS config section could show "Tailscale not running — DNS config unavailable" or fall back to the LAN IP. The machine is unreachable via overlay anyway, so DNS config for it isn't immediately useful.

5. **Should there be a `/config/dns` JSON endpoint for automation?** Not needed yet. If a future `cove join` command automates multi-machine setup, it can parse the HTML or we can add JSON then. YAGNI.
