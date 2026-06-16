# /config/* — Machine Configuration Endpoints

When you add a second device to your Cove setup — another laptop, a phone, a VM — you need the root CA cert from an existing machine so TLS works. You also need DNS configured so `*.cove.<slug>` names resolve to the right machine.

`/config/*` paths on nginx serve these artifacts. You hit them via any IP that reaches the machine — LAN IP, Tailscale IP, direct connection. No hostname needed. This is the bootstrap surface: you reach it before DNS is wired up, get the CA cert and DNS config, then DNS works and you use proper hostnames from then on.

## The Endpoints

### `/config/` — Human-Readable Info Page

An HTML page showing the machine's identity, all available endpoints with direct URLs, and platform-specific instructions.

```
GET http://<lan-ip>:8080/config/
GET https://<ts-ip>:8443/config/
```

```html
<!DOCTYPE html>
<html>
<head><title>Cove — {{ ansible_hostname }}</title></head>
<body>
  <h1>Cove on {{ ansible_hostname }}</h1>

  <h2>Endpoints</h2>
  <ul>
    <li><a href="/config/ca">/config/ca</a> — root CA certificate (PEM download)</li>
    <li><a href="/config/dns">/config/dns</a> — DNS setup (auto-detects your OS)</li>
    <li><a href="/config/dns/macos">/config/dns/macos</a> — macOS DNS script</li>
    <li><a href="/config/dns/linux">/config/dns/linux</a> — Linux DNS script</li>
    <li><a href="/config/dns/windows">/config/dns/windows</a> — Windows DNS script</li>
    <li><a href="/config/dns/ios">/config/dns/ios</a> — iOS CA profile</li>
    <li><a href="/config/dns/android">/config/dns/android</a> — Android instructions</li>
  </ul>

  <h2>Trust this machine</h2>
  <p>Download <a href="/config/ca">/config/ca</a> and install the root CA certificate.</p>
  <p>macOS: double-click → Keychain → mark as trusted.<br>
     Linux: <code>sudo trust anchor cove-root-ca.pem</code><br>
     Windows: <code>certutil -addstore Root cove-root-ca.pem</code><br>
     iOS: use <a href="/config/dns/ios">/config/dns/ios</a> for one-tap profile install.</p>

  <h2>Reach this machine</h2>
  <p>Once DNS is configured, these names resolve to this machine:</p>
  <ul>
    <li><code>git.cove.{{ ansible_hostname }}</code> — forge</li>
    <li><code>vault.cove.{{ ansible_hostname }}</code> — vault</li>
  </ul>

  <h2>Configure DNS</h2>
  <p>Use <a href="/config/dns">/config/dns</a> (auto-detect) or pick your platform:</p>

  <h3>macOS</h3>
  <p><code>curl /config/dns/macos | sudo bash</code></p>
  <pre># Creates /etc/resolver/cove.{{ ansible_hostname }}:
nameserver {{ ts_ip }}
port 5353</pre>

  <h3>Linux</h3>
  <p><code>curl /config/dns/linux | sudo bash</code></p>
  <pre># Creates /etc/dnsmasq.d/cove-{{ ansible_hostname }}.conf:
server=/cove.{{ ansible_hostname }}/{{ ts_ip }}#5353</pre>

  <h3>Windows</h3>
  <p><code>irm /config/dns/windows | iex</code> (admin PowerShell)</p>
  <pre># Adds to hosts file:
{{ ts_ip }} git.cove.{{ ansible_hostname }} vault.cove.{{ ansible_hostname }}</pre>

  <h3>iOS</h3>
  <p>Open <a href="/config/dns/ios">/config/dns/ios</a> in Safari → Install Profile.</p>

  <h3>Android</h3>
  <p><a href="/config/dns/android">/config/dns/android</a> — manual instructions.</p>

  <p>DNS IP: <code>{{ ts_ip }}</code> (Tailscale)</p>
</body>
</html>
```

Rendered from a Jinja2 template at provision time with `{{ ansible_hostname }}` and `{{ ts_ip }}`.

### `/config/ca` — Root CA Certificate Download

The mkcert root CA public cert as a PEM file. Always a raw download — no HTML wrapper.

```
GET https://<ip>/config/ca
→ Content-Type: application/x-pem-file
→ Content-Disposition: attachment; filename="cove-root-ca.pem"
```

### `/config/dns` — Auto-Detect DNS Setup

Auto-detects the requesting device from User-Agent and serves the right artifact for that platform. No JSON, no manual copy-paste.

| Platform | Served | What the user does |
|----------|--------|-------------------|
| macOS | Shell script | `curl .../config/dns \| sudo bash` |
| Linux | Shell script | `curl .../config/dns \| sudo bash` |
| Windows | PowerShell script | `irm .../config/dns \| iex` (or download + run) |
| iOS | `.mobileconfig` profile | Safari downloads → Settings → Profile → Install |
| Android | Plain text instructions | Nothing auto-applicable; shows manual steps |
| Unknown | Plain text instructions | Shows all platform options |

### `/config/dns/{target}` — Explicit Platform DNS Setup

Bypass auto-detection. Request the DNS config for a specific platform directly:

| Path | Platform |
|------|----------|
| `/config/dns/macos` | macOS shell script |
| `/config/dns/linux` | Linux shell script |
| `/config/dns/windows` | Windows PowerShell script |
| `/config/dns/ios` | iOS `.mobileconfig` profile |
| `/config/dns/android` | Android plain text instructions |

Useful when downloading from a different device than the target (e.g., on a MacBook, fetching the Linux script to scp to a server), or when User-Agent detection gets it wrong.

**macOS script:**
```bash
#!/bin/bash
set -e
RESOLVER_DIR="/etc/resolver"
RESOLVER_FILE="$RESOLVER_DIR/cove.mbpbk"
if [ "$EUID" -ne 0 ]; then
    echo "This script needs sudo to write to /etc/resolver/"
    exec sudo bash "$0"
fi
mkdir -p "$RESOLVER_DIR"
cat > "$RESOLVER_FILE" <<EOF
nameserver 100.64.0.5
port 5353
EOF
echo "DNS resolver configured: $RESOLVER_FILE"
echo "Test: dscacheutil -q host -a name git.cove.mbpbk"
```

**Linux script (dnsmasq):**
```bash
#!/bin/bash
set -e
CONF_FILE="/etc/dnsmasq.d/cove-mbpbk.conf"
if [ "$EUID" -ne 0 ]; then
    exec sudo bash "$0"
fi
cat > "$CONF_FILE" <<EOF
server=/cove.mbpbk/100.64.0.5#5353
EOF
if systemctl is-active --quiet dnsmasq; then
    systemctl restart dnsmasq
    echo "dnsmasq restarted with new config"
else
    echo "Config written to $CONF_FILE"
    echo "Start dnsmasq or reload it to apply"
fi
echo "Test: dig git.cove.mbpbk"
```

**Windows PowerShell script:**
```powershell
# Requires admin
if (-not ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")) {
    Write-Error "Run as Administrator"
    exit 1
}
# Windows DNS: add a conditional forwarder or use hosts file
# hosts file is the simplest cross-platform approach
$hostsPath = "$env:SystemRoot\System32\drivers\etc\hosts"
$entry = "100.64.0.5 git.cove.mbpbk vault.cove.mbpbk"
if (-not (Select-String -Path $hostsPath -Pattern "cove.mbpbk" -SimpleMatch)) {
    Add-Content -Path $hostsPath -Value $entry
    Write-Host "Added to hosts: $entry"
} else {
    Write-Host "Entry already exists"
}
Write-Host "Test: nslookup git.cove.mbpbk"
```

Windows doesn't have `/etc/resolver/` or dnsmasq. The hosts file is the pragmatic answer — same mechanism Cove uses for its own hostnames. A conditional forwarder via `Add-DnsClientNrptRule` would be cleaner but requires the DNS Client service and is Windows Server-specific. Hosts file works everywhere.

**iOS `.mobileconfig` profile:**
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>PayloadContent</key>
    <array>
        <dict>
            <key>PayloadDescription</key>
            <string>Configures DNS resolution for *.cove.mbpbk</string>
            <key>PayloadDisplayName</key>
            <string>Cove DNS — mbpbk</string>
            <key>PayloadIdentifier</key>
            <string>cove.dns.mbpbk</string>
            <key>PayloadType</key>
            <string>com.apple.dnsSettings.managed</string>
            <key>PayloadUUID</key>
            <string>$(uuidgen)</string>
            <key>PayloadVersion</key>
            <integer>1</integer>
            <key>DNSSettings</key>
            <dict>
                <key>DNSProtocol</key>
                <string>HTTPS</string>
                <key>ServerAddresses</key>
                <array>
                    <string>100.64.0.5</string>
                </array>
                <key>ServerURL</key>
                <string>https://100.64.0.5:5353/dns-query</string>
                <key>SupplementalMatchDomains</key>
                <array>
                    <string>cove.mbpbk</string>
                </array>
            </dict>
        </dict>
    </array>
    <key>PayloadDisplayName</key>
    <string>Cove DNS — mbpbk</string>
    <key>PayloadIdentifier</key>
    <string>cove.dns.mbpbk</string>
    <key>PayloadType</key>
    <string>Configuration</string>
    <key>PayloadUUID</key>
    <string>$(uuidgen)</string>
    <key>PayloadVersion</key>
    <integer>1</integer>
</dict>
</plist>
```

Wait — dnsmasq doesn't speak DNS-over-HTTPS. The `.mobileconfig` DNS Settings payload requires DoH or DoT. dnsmasq is plain UDP/TCP DNS. iOS can't use it directly via a configuration profile.

**Revised iOS approach:** A `.mobileconfig` that installs the root CA cert (not DNS). DNS on iOS stays manual or uses Tailscale MagicDNS. The `/config/dns` endpoint for iOS serves the CA cert profile instead — that's what iOS can actually auto-install.

Actually, let me reconsider. The user said `/config/dns` should auto-detect and serve a script or file for each platform. For iOS, the useful thing is the CA cert profile. For Android, it's instructions. Let me be honest about what each platform can do.

Let me rewrite this properly.</think>

<｜DSML｜tool_calls>
<｜DSML｜invoke name="write">
<｜DSML｜parameter name="content" string="true"># /config/* — Machine Configuration Endpoints

When you add a second device to your Cove setup — another laptop, a phone, a VM — you need the root CA cert from an existing machine so TLS works. You also need DNS configured so `*.cove.<slug>` names resolve to the right machine.

`/config/*` paths on nginx serve these artifacts. You hit them via any IP that reaches the machine — LAN IP, Tailscale IP, direct connection. No hostname needed. This is the bootstrap surface: you reach it before DNS is wired up, get the CA cert and DNS config, then DNS works and you use proper hostnames from then on.

## The Endpoints

### `/config/` — Human-Readable Info Page

An HTML page showing the machine's identity, CA cert download link, install instructions per platform, and the DNS resolver configuration. Served on any IP:

```
http://<lan-ip>:8080/config/
https://<ts-ip>:8443/config/
```

Rendered from a Jinja2 template at provision time with `{{ ansible_hostname }}` and `{{ ts_ip }}` (or LAN IP fallback).

### `/config/ca` — Root CA Certificate Download

The mkcert root CA public cert as a PEM file. Always a raw download — no HTML wrapper.

```
GET https://<ip>/config/ca
→ Content-Type: application/x-pem-file
→ Content-Disposition: attachment; filename="cove-root-ca.pem"
```

### `/config/dns` — Platform-Specific DNS Setup

Auto-detects the requesting device from User-Agent and serves the right artifact for that platform. No JSON, no manual copy-paste. Each platform gets what it can actually use.

| Platform | User-Agent match | Served | Content-Type |
|----------|-----------------|--------|-------------|
| macOS | `Macintosh` | Shell script | `text/x-shellscript` |
| Linux | `Linux` (not Android) | Shell script | `text/x-shellscript` |
| Windows | `Windows` | PowerShell script | `text/plain` |
| iOS | `iPhone` or `iPad` or `iPod` | `.mobileconfig` CA profile | `application/x-apple-aspen-config` |
| Android | `Android` | Plain text instructions | `text/plain` |
| Unknown | (default) | Plain text instructions | `text/plain` |

**macOS script** — creates `/etc/resolver/cove.<slug>`:

```bash
#!/bin/bash
set -e
FILE="/etc/resolver/cove.{{ ansible_hostname }}"
if [ "$EUID" -ne 0 ]; then exec sudo bash "$0"; fi
mkdir -p /etc/resolver
cat > "$FILE" <<'EOF'
nameserver {{ ts_ip }}
port 5353
EOF
echo "DNS resolver configured: $FILE"
echo "Test: dscacheutil -q host -a name git.cove.{{ ansible_hostname }}"
```

**Linux script** — creates `/etc/dnsmasq.d/cove-<slug>.conf`:

```bash
#!/bin/bash
set -e
FILE="/etc/dnsmasq.d/cove-{{ ansible_hostname }}.conf"
if [ "$EUID" -ne 0 ]; then exec sudo bash "$0"; fi
cat > "$FILE" <<'EOF'
server=/cove.{{ ansible_hostname }}/{{ ts_ip }}#5353
EOF
if systemctl is-active --quiet dnsmasq 2>/dev/null; then
    systemctl restart dnsmasq
    echo "dnsmasq restarted"
else
    echo "Config written to $FILE — start or reload dnsmasq to apply"
fi
echo "Test: dig git.cove.{{ ansible_hostname }}"
```

**Windows PowerShell script** — adds to hosts file (Windows has no `/etc/resolver/` equivalent; NRPT rules require Enterprise/Server SKUs):

```powershell
#Requires -RunAsAdministrator
$hosts = "$env:SystemRoot\System32\drivers\etc\hosts"
$entry = "{{ ts_ip }} git.cove.{{ ansible_hostname }} vault.cove.{{ ansible_hostname }}"
if (-not (Select-String -Path $hosts -Pattern "cove.{{ ansible_hostname }}" -SimpleMatch -ErrorAction SilentlyContinue)) {
    Add-Content -Path $hosts -Value $entry
    Write-Host "Added: $entry"
} else {
    Write-Host "Entry already exists"
}
Write-Host "Test: nslookup git.cove.{{ ansible_hostname }}"
```

**iOS `.mobileconfig`** — installs the root CA certificate. iOS can't auto-configure plain DNS (only DoH/DoT via profiles, which dnsmasq doesn't speak). But it CAN install a CA cert via a profile. The `/config/dns` endpoint for iOS serves the CA cert wrapped in a `.mobileconfig` so Safari offers one-tap install:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>PayloadContent</key>
    <array>
        <dict>
            <key>PayloadCertificateFileName</key>
            <string>cove-root-ca.pem</string>
            <key>PayloadContent</key>
            <data>
{{ root_ca_b64 }}
            </data>
            <key>PayloadDescription</key>
            <string>Trusts *.cove certificates from mbpbk</string>
            <key>PayloadDisplayName</key>
            <string>Cove Root CA — mbpbk</string>
            <key>PayloadIdentifier</key>
            <string>cove.ca.mbpbk</string>
            <key>PayloadType</key>
            <string>com.apple.security.root</string>
            <key>PayloadUUID</key>
            <string>{{ ca_uuid }}</string>
            <key>PayloadVersion</key>
            <integer>1</integer>
        </dict>
    </array>
    <key>PayloadDisplayName</key>
    <string>Cove Root CA — mbpbk</string>
    <key>PayloadIdentifier</key>
    <string>cove.ca.mbpbk</string>
    <key>PayloadType</key>
    <string>Configuration</string>
    <key>PayloadUUID</key>
    <string>{{ profile_uuid }}</string>
    <key>PayloadVersion</key>
    <integer>1</integer>
</dict>
</plist>
```

The `{{ root_ca_b64 }}` is the base64-encoded root CA cert (PEM without header/footer, or the DER binary base64'd). The UUIDs are generated at template render time (Python `uuid.uuid4()` in Ansible). iOS Safari sees `application/x-apple-aspen-config` and offers "Install Profile" — one tap, then Settings → Install.

**Android** — plain text instructions. Android has no `.mobileconfig` equivalent. CA certs must be installed manually (Settings → Security → Install from storage). DNS cannot be auto-configured for custom domains:

- **Private DNS** (Android 9+) requires DoT — dnsmasq doesn't speak it.
- **Per-network DNS** works (Settings → Wi-Fi → gear icon → Advanced → DNS) but is manual and varies by manufacturer.
- **Tailscale** is the practical answer. With Tailscale on the phone and `--accept-dns` pointing at the tailnet's DNS, MagicDNS handles resolution. No per-network config needed.

The `/config/dns/android` response explains this honestly and points the user at Tailscale:

```
Cove on {{ ansible_hostname }}
===============================

1. Install the root CA certificate:
   Download https://<ip>/config/ca
   Settings → Security → Encryption & credentials →
   Install a certificate → CA certificate
   (Path varies by manufacturer — search "certificate" in Settings)

2. DNS configuration:
   Android cannot auto-configure DNS for *.cove.{{ ansible_hostname }}.
   The simplest path: install Tailscale on your phone, connect to
   your tailnet, and enable MagicDNS. *.cove.{{ ansible_hostname }}
   names will resolve automatically.

   Manual alternative (per Wi-Fi network only):
   Settings → Wi-Fi → [your network] → gear icon →
   Advanced → Private DNS → Off (or use Tailscale)
   Then: IP settings → Static → DNS 1: {{ ts_ip }}

3. Access Cove:
   https://<tailscale-fqdn>/ — Forgejo
   https://<tailscale-fqdn>/config/ — this page
```

### Why Phones Can't Auto-Configure Plain DNS

Both iOS and Android only support encrypted DNS for system-level configuration:

| Platform | Mechanism | Protocol Required | dnsmasq Compatible? |
|----------|-----------|-------------------|---------------------|
| iOS | DNS Settings profile (`.mobileconfig`) | DoH or DoT | Yes — via DoH proxy |
| iOS | Per-network DNS (manual) | Plain DNS | Yes, but per-network only |
| Android | Private DNS (system-wide) | DoT only | No — needs DoT (future) |
| Android | Third-party DoH app (Intra, Nebulo) | DoH | Yes — via DoH proxy |
| Android | Per-network DNS (manual) | Plain DNS | Yes, but per-network only, varies by OEM |

## DoH Proxy

A lightweight DNS-over-HTTPS proxy runs alongside dnsmasq, accepting encrypted DNS queries and forwarding them to dnsmasq over plain UDP. This unlocks iOS auto-configuration (`.mobileconfig` DNS Settings payload) and gives Android a DoH endpoint for third-party apps.

### Architecture

```
Phone (iOS/Android)
  │
  │ DoH POST /dns-query (HTTPS, DNS wire format)
  ▼
nginx (:443)
  │ proxy_pass → doh-proxy:8053
  ▼
doh-proxy (Go binary, internal port 8053)
  │ forward UDP → dnsmasq:5353
  ▼
dnsmasq (:5353)
  │ resolve *.cove.<slug> → <ts-ip>
  ▼
response (DNS wire format)
```

nginx terminates TLS (mkcert `*.cove` cert). The DoH proxy speaks HTTP on one side and DNS on the other. It's a ~100-line Go binary — receives RFC 8484 POST requests with DNS wire format bodies, forwards to dnsmasq via UDP, returns the wire format response.

### Container

The DoH proxy runs in the dnsmasq container alongside dnsmasq. Same network namespace, same lifecycle. No new container, no new port publishing. The Dockerfile adds the Go binary:

```dockerfile
FROM alpine:3.21
RUN apk add --no-cache dnsmasq
COPY cove.conf /etc/dnsmasq.d/cove.conf
COPY doh-proxy /usr/local/bin/doh-proxy
ENTRYPOINT ["sh", "-c", "dnsmasq --no-daemon --conf-dir=/etc/dnsmasq.d & doh-proxy -upstream 127.0.0.1:5353 -listen :8053"]
```

The `doh-proxy` binary is built from source (Go) and committed to the repo, or built in a multi-stage Dockerfile. Flags: `-upstream` is the dnsmasq address, `-listen` is the HTTP listen address.

### nginx

A `/dns-query` location on the default server block and `git.cove` server block:

```nginx
location = /dns-query {
    proxy_pass http://dnsmasq:8053;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
}
```

The DoH proxy only needs the POST body (DNS wire format). Standard proxy headers are fine.

### iOS `.mobileconfig` — Now With Real DNS

With DoH available, the iOS profile includes a DNS Settings payload that configures system-wide resolution for `*.cove.<slug>`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>PayloadContent</key>
    <array>
        <!-- CA cert payload (same as before) -->
        <dict>
            <key>PayloadCertificateFileName</key>
            <string>cove-root-ca.pem</string>
            <key>PayloadContent</key>
            <data>{{ root_ca_b64 }}</data>
            <key>PayloadDescription</key>
            <string>Trusts *.cove certificates from {{ ansible_hostname }}</string>
            <key>PayloadDisplayName</key>
            <string>Cove Root CA — {{ ansible_hostname }}</string>
            <key>PayloadIdentifier</key>
            <string>cove.ca.{{ ansible_hostname }}</string>
            <key>PayloadType</key>
            <string>com.apple.security.root</string>
            <key>PayloadUUID</key>
            <string>{{ ca_uuid }}</string>
            <key>PayloadVersion</key>
            <integer>1</integer>
        </dict>
        <!-- DNS Settings payload -->
        <dict>
            <key>PayloadDescription</key>
            <string>Configures DNS resolution for *.cove.{{ ansible_hostname }}</string>
            <key>PayloadDisplayName</key>
            <string>Cove DNS — {{ ansible_hostname }}</string>
            <key>PayloadIdentifier</key>
            <string>cove.dns.{{ ansible_hostname }}</string>
            <key>PayloadType</key>
            <string>com.apple.dnsSettings.managed</string>
            <key>PayloadUUID</key>
            <string>{{ dns_uuid }}</string>
            <key>PayloadVersion</key>
            <integer>1</integer>
            <key>DNSSettings</key>
            <dict>
                <key>DNSProtocol</key>
                <string>HTTPS</string>
                <key>ServerURL</key>
                <string>https://{{ ts_ip }}:8443/dns-query</string>
                <key>SupplementalMatchDomains</key>
                <array>
                    <string>cove.{{ ansible_hostname }}</string>
                </array>
            </dict>
        </dict>
    </array>
    <key>PayloadDisplayName</key>
    <string>Cove — {{ ansible_hostname }}</string>
    <key>PayloadIdentifier</key>
    <string>cove.{{ ansible_hostname }}</string>
    <key>PayloadType</key>
    <string>Configuration</string>
    <key>PayloadUUID</key>
    <string>{{ profile_uuid }}</string>
    <key>PayloadVersion</key>
    <integer>1</integer>
</dict>
</plist>
```

The `ServerURL` uses the Tailscale IP directly (not a hostname) because the phone doesn't resolve `*.cove` names yet — that's what this profile configures. The `SupplementalMatchDomains` scopes the DoH server to only `*.cove.<slug>` queries; all other DNS goes through the system default. One tap in Safari, Settings → Install, and both the CA cert and DNS are configured.

### Android

Android Private DNS (system-wide) only supports DoT, not DoH. A DoT endpoint would need a separate TLS listener — more complexity than DoH. For now, Android has two paths:

1. **Tailscale** (recommended) — MagicDNS handles resolution. No per-network config.
2. **Third-party DoH app** (Intra, Nebulo, DNSChanger) — point at `https://<ts-ip>:8443/dns-query`. These apps create a local VPN interface that intercepts DNS and forwards via DoH.

The `/config/dns/android` response explains both options. A future DoT endpoint (same proxy, different listener) would unlock system-level Private DNS on Android.

### DoH Proxy Binary

A minimal Go program. The core is ~100 lines:

```go
// doh-proxy: accepts DoH POST /dns-query, forwards to upstream DNS via UDP
package main

import (
    "flag"
    "io"
    "log"
    "net"
    "net/http"
    "time"
)

func main() {
    upstream := flag.String("upstream", "127.0.0.1:5353", "DNS upstream address")
    listen := flag.String("listen", ":8053", "HTTP listen address")
    flag.Parse()

    http.HandleFunc("/dns-query", func(w http.ResponseWriter, r *http.Request) {
        if r.Method != http.MethodPost {
            http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
            return
        }
        body, err := io.ReadAll(r.Body)
        if err != nil || len(body) == 0 {
            http.Error(w, "bad request", http.StatusBadRequest)
            return
        }
        conn, err := net.DialTimeout("udp", *upstream, 5*time.Second)
        if err != nil {
            http.Error(w, "upstream unreachable", http.StatusBadGateway)
            return
        }
        defer conn.Close()
        conn.SetDeadline(time.Now().Add(5 * time.Second))
        if _, err := conn.Write(body); err != nil {
            http.Error(w, "upstream write failed", http.StatusBadGateway)
            return
        }
        resp := make([]byte, 512)
        n, err := conn.Read(resp)
        if err != nil {
            http.Error(w, "upstream read failed", http.StatusBadGateway)
            return
        }
        w.Header().Set("Content-Type", "application/dns-message")
        w.Write(resp[:n])
    })

    log.Printf("DoH proxy listening on %s, upstream %s", *listen, *upstream)
    log.Fatal(http.ListenAndServe(*listen, nil))
}
```

No caching, no recursion, no DNSSEC validation. It's a transparent pipe: DoH in, UDP out, response back. dnsmasq does the actual resolution. The binary is statically compiled (`CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build`) and copied into the dnsmasq Docker image.

### What This Unlocks

| Before DoH | After DoH |
|-----------|----------|
| iOS: manual CA install, no DNS config | iOS: one-tap profile installs CA + DNS |
| Android: manual CA install, Tailscale-only DNS | Android: CA install + DoH app option |
| Desktop: already works via `/config/dns` scripts | Desktop: unchanged (scripts are better than DoH for desktops) |

The DoH proxy is the bridge between encrypted DNS (what phones require) and plain DNS (what dnsmasq speaks). It's a thin pipe — no logic, no caching, just protocol translation.

## nginx Implementation

### User-Agent detection

A `map` block in the nginx config classifies the client OS:

```nginx
map $http_user_agent $config_dns_type {
    default                      "unknown";
    "~*Macintosh"                "macos";
    "~*Windows NT"               "windows";
    "~*Android"                  "android";
    "~*iPhone"                   "ios";
    "~*iPad"                     "ios";
    "~*iPod"                     "ios";
    "~*Linux"                    "linux";
}
```

The `linux` match comes after `android` so Android (which also says "Linux" in UA) is caught first.

### Server blocks

The `/config/*` locations live on the default server block (catches direct IP access) and the `git.cove` server block (host-machine access). The catch-all no longer proxies to Forgejo — Forgejo is only reachable at `git.cove` and `git.cove.<slug>`.

```nginx
# Default server — catches direct IP access (LAN, Tailscale)
server {
    listen 443 ssl default_server;
    listen 80 default_server;
    server_name _;

    ssl_certificate     /certs/cove.local.pem;
    ssl_certificate_key /certs/cove.local-key.pem;

    # HTTP → HTTPS redirect (except /config/ which works on either)
    if ($scheme = http) {
        return 301 https://$host$request_uri;
    }

    location = /config/ {
        alias /etc/nginx/config.html;
        add_header Content-Type text/html;
    }

    location = /config/ca {
        alias /certs/rootCA.pem;
        add_header Content-Type application/x-pem-file;
        add_header Content-Disposition 'attachment; filename="cove-root-ca.pem"';
    }

    location = /config/dns {
        add_header Content-Type text/x-shellscript;
        add_header Content-Disposition 'attachment; filename="cove-dns-setup.sh"';
        alias /etc/nginx/config/dns/$config_dns_type;
    }

    location ~ ^/config/dns/(macos|linux|windows|ios|android)$ {
        alias /etc/nginx/config/dns/$1;
        add_header Content-Type text/x-shellscript;
        add_header Content-Disposition 'attachment; filename="cove-dns-setup.sh"';
    }

    # Everything else: close the connection (no Forgejo proxy)
    location / {
        return 444;
    }
}
```

The `/config/dns` location uses `alias` with the `$config_dns_type` variable to serve different files from `/etc/nginx/config/dns/macos`, `/etc/nginx/config/dns/linux`, etc. These files are rendered from Jinja2 templates at provision time.

### git.cove server block

Same `/config/*` locations, plus the Forgejo proxy:

```nginx
server {
    listen 443 ssl;
    server_name git.cove cove;

    ssl_certificate     /certs/cove.local.pem;
    ssl_certificate_key /certs/cove.local-key.pem;

    location = /config/ {
        alias /etc/nginx/config.html;
        add_header Content-Type text/html;
    }

    location = /config/ca {
        alias /certs/rootCA.pem;
        add_header Content-Type application/x-pem-file;
        add_header Content-Disposition 'attachment; filename="cove-root-ca.pem"';
    }

    location = /config/dns {
        add_header Content-Type text/x-shellscript;
        add_header Content-Disposition 'attachment; filename="cove-dns-setup.sh"';
        alias /etc/nginx/config/dns/$config_dns_type;
    }

    location ~ ^/config/dns/(macos|linux|windows|ios|android)$ {
        alias /etc/nginx/config/dns/$1;
        add_header Content-Type text/x-shellscript;
        add_header Content-Disposition 'attachment; filename="cove-dns-setup.sh"';
    }

    location / {
        proxy_pass http://forgejo_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

### Per-machine git.cove regex block

```nginx
server {
    listen 443 ssl;
    server_name ~^git\.cove\.[a-zA-Z0-9-]+$ ~^cove\.[a-zA-Z0-9-]+$;

    ssl_certificate     /certs/cove.local.pem;
    ssl_certificate_key /certs/cove.local-key.pem;

    location = /config/ {
        alias /etc/nginx/config.html;
        add_header Content-Type text/html;
    }

    location = /config/ca {
        alias /certs/rootCA.pem;
        add_header Content-Type application/x-pem-file;
        add_header Content-Disposition 'attachment; filename="cove-root-ca.pem"';
    }

    location = /config/dns {
        add_header Content-Type text/x-shellscript;
        add_header Content-Disposition 'attachment; filename="cove-dns-setup.sh"';
        alias /etc/nginx/config/dns/$config_dns_type;
    }

    location ~ ^/config/dns/(macos|linux|windows|ios|android)$ {
        alias /etc/nginx/config/dns/$1;
        add_header Content-Type text/x-shellscript;
        add_header Content-Disposition 'attachment; filename="cove-dns-setup.sh"';
    }

    location / {
        proxy_pass http://forgejo_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

## Templates and Provisioning

### Files rendered at `cove up` time

| Template | Rendered to | Mounted in nginx |
|----------|------------|-----------------|
| `compose/nginx/config.html.j2` | `{{ cove_data_root }}/nginx/config.html` | `/etc/nginx/config.html` |
| `compose/nginx/config/dns/macos.j2` | `{{ cove_data_root }}/nginx/config/dns/macos` | `/etc/nginx/config/dns/macos` |
| `compose/nginx/config/dns/linux.j2` | `{{ cove_data_root }}/nginx/config/dns/linux` | `/etc/nginx/config/dns/linux` |
| `compose/nginx/config/dns/windows.j2` | `{{ cove_data_root }}/nginx/config/dns/windows` | `/etc/nginx/config/dns/windows` |
| `compose/nginx/config/dns/ios.j2` | `{{ cove_data_root }}/nginx/config/dns/ios` | `/etc/nginx/config/dns/ios` |
| `compose/nginx/config/dns/android.j2` | `{{ cove_data_root }}/nginx/config/dns/android` | `/etc/nginx/config/dns/android` |
| `compose/nginx/config/dns/unknown.j2` | `{{ cove_data_root }}/nginx/config/dns/unknown` | `/etc/nginx/config/dns/unknown` |

### Template variables

All templates receive:
- `{{ ansible_hostname }}` — machine slug (e.g., `mbpbk`)
- `{{ ts_ip }}` — Tailscale IP (e.g., `100.64.0.5`), or LAN IP fallback
- `{{ root_ca_b64 }}` — base64-encoded root CA cert (for iOS `.mobileconfig`)
- `{{ ca_uuid }}`, `{{ profile_uuid }}` — generated UUIDs (for iOS `.mobileconfig`)

### Data directory additions

```
~/Documents/cove-data/nginx/
├── config.html
└── config/
    └── dns/
        ├── macos
        ├── linux
        ├── windows
        ├── ios
        ├── android
        └── unknown
```

### Volume mounts

```yaml
nginx:
  volumes:
    - ${COVE_DATA_ROOT}/nginx/config.html:/etc/nginx/config.html:ro
    - ${COVE_DATA_ROOT}/nginx/config/dns:/etc/nginx/config/dns:ro
    - ${MKCERT_CAROOT}/rootCA.pem:/certs/rootCA.pem:ro
```

## Bootstrap Flow

### From a phone (iOS)

1. Open `https://<ts-ip>:8443/config/` in Safari. Accept the TLS warning (you're about to fix it).
2. Page shows machine identity, CA cert download link, and a note about DNS.
3. Tap `/config/dns` → Safari downloads a `.mobileconfig` profile → "Install Profile" → Settings → Install → CA cert trusted.
4. Now `https://<tailscale-fqdn>/` works with valid TLS. Bookmark it.
5. DNS for `*.cove.<slug>` names isn't auto-configurable on iOS. Use the Tailscale FQDN or MagicDNS.

### From a phone (Android)

1. Open `https://<ts-ip>:8443/config/` in Chrome. Accept the TLS warning.
2. Download `/config/ca` → Settings → Security → Install certificate → CA certificate.
3. `/config/dns` shows text instructions. Android can't auto-configure DNS for custom domains.
4. Use the Tailscale FQDN for access.

### From a new macOS laptop

1. `curl -k https://<ts-ip>:8443/config/dns | sudo bash` — installs CA cert? No, that's `/config/ca`. Let me fix this.

Actually, the flow is two steps:

1. `curl -kO https://<ts-ip>:8443/config/ca` → double-click → Keychain → trust.
2. `curl -k https://<ts-ip>:8443/config/dns | sudo bash` → creates `/etc/resolver/cove.<slug>`.
3. `dig git.cove.<slug>` resolves. `https://git.cove.<slug>/` works with valid TLS.

### From a new Linux laptop

1. `curl -kO https://<ts-ip>:8443/config/ca` → `sudo trust anchor cove-root-ca.pem`.
2. `curl -k https://<ts-ip>:8443/config/dns | sudo bash` → creates dnsmasq config, restarts dnsmasq.
3. `dig git.cove.<slug>` resolves.

### From a new Windows laptop

1. Download `https://<ts-ip>:8443/config/ca` → `certutil -addstore Root cove-root-ca.pem`.
2. Download and run the PowerShell script from `/config/dns` → adds hosts entries.
3. `nslookup git.cove.<slug>` resolves.

## What This Replaces

- The `ca.cove` subdomain from the root-cert-distribution musing — absorbed into `/config/ca`.
- The catch-all → Forgejo proxy — removed. Forgejo is only at `git.cove` and `git.cove.<slug>`. The default server block serves `/config/*` and returns 444 for everything else.

## Open Questions

1. **Should `/config/dns` for iOS also be served at `/config/ca` when iOS is detected?** Currently `/config/ca` always serves raw PEM (works for manual install on any platform). `/config/dns` for iOS serves the `.mobileconfig` wrapper (one-tap install). They're different paths for different use cases. Could merge them — `/config/ca` auto-detects iOS and serves `.mobileconfig` — but that breaks `curl` usage. Keep them separate.

2. **What about the Tailscale IP when Tailscale is down?** `ts_ip` falls back to the LAN IP (from `ansible_default_ipv4.address`). The DNS config is still useful on the LAN. The `/config/` page notes which IP is being published.

3. **Should the macOS/Linux scripts also install the CA cert?** They could — `curl -O /config/ca && security add-trusted-cert ...` on macOS, `trust anchor` on Linux. But that couples the DNS script to CA install. Two separate steps is clearer: the operator sees what each step does.

4. **Does the default server block need HTTP (port 80)?** Yes — for `http://<lan-ip>:8080/config/` access. The redirect to HTTPS will fail TLS verification until the CA is installed, but `/config/` on HTTP is fine (it's just an info page, no secrets). The `/config/ca` download should be HTTPS to avoid MITM of the root cert itself. So: `/config/` works on HTTP, `/config/ca` and `/config/dns` redirect to HTTPS.

5. **Should `cove up` print the bootstrap URL?** After bringup: "Bootstrap: http://<lan-ip>:8080/config/ or https://<ts-ip>:8443/config/". Low effort, high discoverability.
