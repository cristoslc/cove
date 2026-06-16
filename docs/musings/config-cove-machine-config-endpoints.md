# config.cove — Machine Configuration Endpoints

When you add a second Cove machine to your setup, you need three things from the first machine to configure the second: its root CA cert (so TLS works), its DNS resolver address (so `*.cove.<slug>` names resolve), and its machine identity (the slug itself). Currently you figure these out manually — find the CAROOT path, run `tailscale status`, copy files around.

`config.cove` is a subdomain that serves these configuration artifacts over HTTPS. A new machine (or a phone, or a VM) hits one endpoint, gets what it needs, and configures itself.

## The Endpoints

All served under `config.cove.<machine-slug>` (canonical) and at `/config/` paths on the catch-all (remote-device fallback).

### `/ca` — Root CA Certificate

The mkcert root CA public cert. Install this on any device that needs to trust `*.cove` TLS certificates from this machine.

```
GET https://config.cove.mbpbk/ca
→ Content-Type: application/x-pem-file
→ Content-Disposition: attachment; filename="cove-mbpbk-root-ca.pem"
→ <rootCA.pem contents>
```

Same as the `ca.cove` concept from the earlier musing, moved under `config.cove/` for grouping.

### `/dns` — DNS Resolver Configuration

Machine identity and resolver info in JSON. A remote machine hits this endpoint to learn how to resolve `*.cove.<slug>` names pointing at this machine.

```
GET https://config.cove.mbpbk/dns
→ Content-Type: application/json
```

```json
{
  "machine": "mbpbk",
  "domain": "cove.mbpbk",
  "dns_ip": "100.64.0.5",
  "dns_port": 5353,
  "resolver": {
    "macos": {
      "path": "/etc/resolver/cove.mbpbk",
      "content": "nameserver 100.64.0.5\nport 5353\n"
    },
    "linux_dnsmasq": {
      "path": "/etc/dnsmasq.d/cove-mbpbk.conf",
      "directive": "server=/cove.mbpbk/100.64.0.5#5353"
    }
  }
}
```

The `resolver` field has platform-specific snippets. The raw fields (`dns_ip`, `dns_port`, `domain`) are the authoritative data — the snippets are pre-rendered convenience. A script or human can use either.

### `/` — Index

Lists available endpoints:

```
GET https://config.cove.mbpbk/
→ Content-Type: application/json
```

```json
{
  "machine": "mbpbk",
  "endpoints": {
    "ca": "/ca",
    "dns": "/dns"
  }
}
```

## nginx Implementation

### `config.cove` server block (host-machine access)

```nginx
# config.cove — machine configuration endpoints
server {
    listen 443 ssl;
    server_name config.cove;

    ssl_certificate     /certs/cove.local.pem;
    ssl_certificate_key /certs/cove.local-key.pem;

    location = /ca {
        alias /certs/rootCA.pem;
        add_header Content-Type application/x-pem-file;
        add_header Content-Disposition 'attachment; filename="cove-root-ca.pem"';
    }

    location = /dns {
        add_header Content-Type application/json;
        return 200 '{"machine":"{{ ansible_hostname }}","domain":"cove.{{ ansible_hostname }}","dns_ip":"{{ ts_ip }}","dns_port":5353,"resolver":{"macos":{"path":"/etc/resolver/cove.{{ ansible_hostname }}","content":"nameserver {{ ts_ip }}\\nport 5353\\n"},"linux_dnsmasq":{"path":"/etc/dnsmasq.d/cove-{{ ansible_hostname }}.conf","directive":"server=/cove.{{ ansible_hostname }}/{{ ts_ip }}#5353"}}}';
    }

    location = / {
        add_header Content-Type application/json;
        return 200 '{"machine":"{{ ansible_hostname }}","endpoints":{"ca":"/ca","dns":"/dns"}}';
    }
}
```

### Per-machine regex block (Cove-to-Cove access)

```nginx
# config.cove.<slug> — per-machine config endpoints
server {
    listen 443 ssl;
    server_name ~^config\.cove\.[a-zA-Z0-9-]+$;

    ssl_certificate     /certs/cove.local.pem;
    ssl_certificate_key /certs/cove.local-key.pem;

    location = /ca {
        alias /certs/rootCA.pem;
        add_header Content-Type application/x-pem-file;
        add_header Content-Disposition 'attachment; filename="cove-root-ca.pem"';
    }

    location = /dns {
        add_header Content-Type application/json;
        return 200 '{"machine":"{{ ansible_hostname }}","domain":"cove.{{ ansible_hostname }}","dns_ip":"{{ ts_ip }}","dns_port":5353,"resolver":{"macos":{"path":"/etc/resolver/cove.{{ ansible_hostname }}","content":"nameserver {{ ts_ip }}\\nport 5353\\n"},"linux_dnsmasq":{"path":"/etc/dnsmasq.d/cove-{{ ansible_hostname }}.conf","directive":"server=/cove.{{ ansible_hostname }}/{{ ts_ip }}#5353"}}}';
    }

    location = / {
        add_header Content-Type application/json;
        return 200 '{"machine":"{{ ansible_hostname }}","endpoints":{"ca":"/ca","dns":"/dns"}}';
    }
}
```

### Catch-all fallback (remote-device access via Tailscale FQDN)

```nginx
# In the catch-all (default) server block:
location = /config/ca {
    alias /certs/rootCA.pem;
    add_header Content-Type application/x-pem-file;
    add_header Content-Disposition 'attachment; filename="cove-root-ca.pem"';
}

location = /config/dns {
    add_header Content-Type application/json;
    return 200 '{"machine":"{{ ansible_hostname }}","domain":"cove.{{ ansible_hostname }}","dns_ip":"{{ ts_ip }}","dns_port":5353,"resolver":{"macos":{"path":"/etc/resolver/cove.{{ ansible_hostname }}","content":"nameserver {{ ts_ip }}\\nport 5353\\n"},"linux_dnsmasq":{"path":"/etc/dnsmasq.d/cove-{{ ansible_hostname }}.conf","directive":"server=/cove.{{ ansible_hostname }}/{{ ts_ip }}#5353"}}}';
}
```

From a phone on Tailscale: `https://<tailscale-fqdn>/config/ca` downloads the root CA, `https://<tailscale-fqdn>/config/dns` shows the resolver config. From another Cove machine: `https://config.cove.mbpbk/dns` (resolved via the resolver file for `cove.mbpbk`).

## TLS Coverage

`config.cove` is added to the mkcert SAN list. `config.cove.<slug>` is covered by the `*.cove.<slug>` wildcard already in the cert. The catch-all paths use the Tailscale cert when accessed via Tailscale FQDN.

## One Resolution Per Machine

The `dns_ip` in the config endpoint is the overlay network IP — Tailscale today, could be Nebula or Wireguard tomorrow. No separate LAN resolution. Rationale:

- **LAN IPs are ephemeral.** They change when you switch networks (home, café, office). Tailscale IPs are stable for the life of the node key.
- **Tailscale uses direct LAN connections when possible.** The Tailscale IP is reachable from the same LAN with no extra hop. There's no performance reason to prefer the LAN IP.
- **One IP to maintain.** The machine knows its Tailscale IP (from `tailscale status --json`). Adding LAN IP detection means picking the right interface, handling multi-homed machines, and updating when DHCP changes.
- **The overlay network is the connectivity layer.** Cove assumes an overlay for machine-to-machine communication. Whether that's Tailscale, Nebula, or Wireguard is an implementation detail. The config endpoint publishes whatever IP the overlay uses.

If someone isn't using an overlay network at all (two machines on the same LAN, no Tailscale), they can still use the mechanism — they'd set `ts_ip` to their LAN IP in host_vars. But the default and documented path assumes an overlay.

## What This Replaces

The `ca.cove` subdomain from the earlier root-cert-distribution musing is absorbed into `config.cove/ca`. The standalone `ca.cove` server block becomes unnecessary — `config.cove` serves the same cert at `/ca`. The `/ca` catch-all path becomes `/config/ca`.

## Configuration Flow for a New Machine

1. **New machine boots, Tailscale is up.** It can reach existing machines via their Tailscale IPs.
2. **Install root CA.** `curl -o cove-root-ca.pem https://<existing-tailscale-fqdn>/config/ca` → install in keychain.
3. **Get DNS resolver config.** `curl https://<existing-tailscale-fqdn>/config/dns` → shows the resolver snippet.
4. **Add resolver file.** Copy the `macos.content` or `linux_dnsmasq.directive` into the appropriate config path.
5. **Verify.** `dig git.cove.mbpbk` resolves to the existing machine's Tailscale IP.
6. **Repeat for each peer machine.**

After step 4, `*.cove.<slug>` names resolve for that peer. The new machine can now use `https://config.cove.mbpbk/dns` (the canonical name) instead of the Tailscale FQDN for future config lookups.

## Open Questions

1. **Should `config/dns` also serve a setup script?** A `curl ... | sudo bash` one-liner that creates the resolver file would be convenient but is a security anti-pattern. The JSON response with platform-specific snippets is safer — the operator reads it and decides.

2. **Should the index page be HTML instead of JSON?** A human-friendly page with download buttons and copy-paste snippets would be nicer than raw JSON. But JSON is machine-parseable and trivially simple. HTML can come later as polish.

3. **What about the Tailscale IP when Tailscale is down?** If Tailscale isn't running, `ts_ip` is unavailable. The `/dns` endpoint could return `null` for `dns_ip` or omit the endpoint entirely. The machine is unreachable anyway, so DNS config for it isn't useful.

4. **Should `cove up` print the config URLs?** After bringup, print: "Config endpoints: https://config.cove.<hostname>/ca, https://config.cove.<hostname>/dns". Low effort, high discoverability.

5. **Does this need its own nginx include file or is it part of the main template?** Part of the main template. These are Cove services, not user-defined routes. They belong in `default.conf.j2` alongside the forge/vault/pages blocks.
