# DNS Infrastructure Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Cove's DNS layer a first-class infrastructure service — per-machine identity, remote resolution, bootstrap endpoints, DoH proxy for phones, and user-defined HTTP routing.

**Architecture:** dnsmasq publishes per-machine identity (`*.cove.<slug>` → machine IP). nginx serves `/config/*` bootstrap endpoints (CA cert, platform-specific DNS scripts, DoH proxy). A `user.d` include directory lets users add HTTP routes for their own `*.cove` hostnames. A ~100-line Go DoH proxy in the dnsmasq container bridges encrypted DNS (phones) to plain DNS (dnsmasq).

**Tech Stack:** dnsmasq, nginx, mkcert, Ansible (Jinja2 templates), Go (doh-proxy binary)

**Specs:**
- `docs/musings/dns-as-cove-infrastructure.md`
- `docs/musings/per-machine-dns-names.md`
- `docs/musings/config-cove-machine-config-endpoints.md`
- `docs/musings/non-http-services-and-dns.md`
- `docs/musings/ca-cove-root-cert-distribution.md`

---

## Chunk 1: dnsmasq — Per-Machine Identity + DoH Proxy

### Task 1.1: Update dnsmasq config template

**Files:**
- Modify: `compose/dnsmasq/cove.conf.j2`

- [ ] **Step 1: Add per-machine identity rule**

Add `address=/cove.{{ ansible_hostname }}/{{ ts_ip }}` after the existing `address=/cove/127.0.0.1` line. The template now receives `ansible_hostname` (from gather_facts) and `ts_ip` (new variable, set in bringup.yml in Chunk 4).

```diff
 address=/cove/127.0.0.1
+address=/cove.{{ ansible_hostname }}/{{ ts_ip }}
 bind-interfaces
```

- [ ] **Step 2: Verify template renders**

Run: `python3 -c "from jinja2 import Template; t = Template(open('compose/dnsmasq/cove.conf.j2').read()); print(t.render(ansible_hostname='mbpbk', ts_ip='100.64.0.5'))"`
Expected: Output contains both `address=/cove/127.0.0.1` and `address=/cove.mbpbk/100.64.0.5`

- [ ] **Step 3: Commit**

```bash
git add compose/dnsmasq/cove.conf.j2
git commit -m "feat: per-machine DNS identity in dnsmasq template"
```

### Task 1.2: Create DoH proxy Go binary

**Files:**
- Create: `compose/dnsmasq/doh-proxy/main.go`
- Create: `compose/dnsmasq/doh-proxy` (compiled binary)

- [ ] **Step 1: Write Go source**

```go
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

- [ ] **Step 2: Compile binary**

Run: `cd compose/dnsmasq/doh-proxy && CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build -o ../doh-proxy .`
Expected: `doh-proxy` binary appears at `compose/dnsmasq/doh-proxy` (no output on success)

- [ ] **Step 3: Verify binary is static**

Run: `file compose/dnsmasq/doh-proxy`
Expected: Output contains "statically linked"

- [ ] **Step 4: Commit**

```bash
git add compose/dnsmasq/doh-proxy/main.go compose/dnsmasq/doh-proxy
git commit -m "feat: DoH proxy — Go binary, forwards DoH to dnsmasq UDP"
```

### Task 1.3: Update dnsmasq Dockerfile

**Files:**
- Modify: `compose/dnsmasq/Dockerfile`

- [ ] **Step 1: Add doh-proxy binary and update entrypoint**

```dockerfile
FROM alpine:3.21
RUN apk add --no-cache dnsmasq
# Fallback config; overridden by volume mount in docker-compose.yml
COPY cove.conf /etc/dnsmasq.d/cove.conf
COPY doh-proxy /usr/local/bin/doh-proxy
ENTRYPOINT ["sh", "-c", "dnsmasq --no-daemon --conf-dir=/etc/dnsmasq.d & doh-proxy -upstream 127.0.0.1:5353 -listen :8053"]
```

- [ ] **Step 2: Verify image builds**

Run: `docker build -t cove-dnsmasq-test compose/dnsmasq/`
Expected: Build succeeds, no errors

- [ ] **Step 3: Commit**

```bash
git add compose/dnsmasq/Dockerfile
git commit -m "feat: dnsmasq container runs DoH proxy alongside dnsmasq"
```

---

## Chunk 2: nginx — Config Template Rewrite

### Task 2.1: Rewrite nginx default.conf.j2

**Files:**
- Modify: `compose/nginx/default.conf.j2`

- [ ] **Step 1: Write the complete new template**

The template needs these changes from the current 118-line file:
1. Add `map $http_user_agent $config_dns_type` block at top (User-Agent → platform classification)
2. Add `include /etc/nginx/user.d/*.conf;` after upstreams
3. Replace the standalone HTTP redirect server block — move into default server
4. Replace the catch-all server block — no longer proxies to Forgejo; serves `/config/*` and `/dns-query`, returns 444 for everything else
5. Replace the git.cove server block — add `/config/*` and `/dns-query` locations before the Forgejo proxy
6. Add per-machine forge regex block: `~^git\.cove\.[a-zA-Z0-9-]+$ ~^cove\.[a-zA-Z0-9-]+$`
7. Add per-machine vault regex block: `~^vault\.cove\.[a-zA-Z0-9-]+$`
8. Keep hc.cove, vault.cove, *.pages.cove, and Tailscale FQDN blocks unchanged

Full template content:

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

upstream forgejo_backend {
    server forgejo:3000;
}

upstream vault_backend {
    server vault:8200;
}

include /etc/nginx/user.d/*.conf;

# Default server — catches direct IP access (LAN, Tailscale)
server {
    listen 443 ssl default_server;
    listen 80 default_server;
    server_name _;

    ssl_certificate     /certs/cove.local.pem;
    ssl_certificate_key /certs/cove.local-key.pem;

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
        alias /etc/nginx/config/dns/$config_dns_type;
        add_header Content-Type text/x-shellscript;
        add_header Content-Disposition 'attachment; filename="cove-dns-setup.sh"';
    }

    location ~ ^/config/dns/(macos|linux|windows|ios|android)$ {
        alias /etc/nginx/config/dns/$1;
        add_header Content-Type text/x-shellscript;
        add_header Content-Disposition 'attachment; filename="cove-dns-setup.sh"';
    }

    location = /dns-query {
        proxy_pass http://dnsmasq:8053;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location / {
        return 444;
    }
}

# hc.cove — health check endpoint
server {
    listen 443 ssl;
    server_name hc.cove;

    ssl_certificate     /certs/cove.local.pem;
    ssl_certificate_key /certs/cove.local-key.pem;

    location / {
        return 200 "cove ingress ok\n";
        add_header Content-Type text/plain;
    }
}

# git.cove — forgejo
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
        alias /etc/nginx/config/dns/$config_dns_type;
        add_header Content-Type text/x-shellscript;
        add_header Content-Disposition 'attachment; filename="cove-dns-setup.sh"';
    }

    location ~ ^/config/dns/(macos|linux|windows|ios|android)$ {
        alias /etc/nginx/config/dns/$1;
        add_header Content-Type text/x-shellscript;
        add_header Content-Disposition 'attachment; filename="cove-dns-setup.sh"';
    }

    location = /dns-query {
        proxy_pass http://dnsmasq:8053;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location / {
        proxy_pass http://forgejo_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}

# vault.cove — vault UI
server {
    listen 443 ssl;
    server_name vault.cove;

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

# Per-machine forge — git.cove.<slug> and cove.<slug>
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
        alias /etc/nginx/config/dns/$config_dns_type;
        add_header Content-Type text/x-shellscript;
        add_header Content-Disposition 'attachment; filename="cove-dns-setup.sh"';
    }

    location ~ ^/config/dns/(macos|linux|windows|ios|android)$ {
        alias /etc/nginx/config/dns/$1;
        add_header Content-Type text/x-shellscript;
        add_header Content-Disposition 'attachment; filename="cove-dns-setup.sh"';
    }

    location = /dns-query {
        proxy_pass http://dnsmasq:8053;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

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
        alias /etc/nginx/config/dns/$config_dns_type;
        add_header Content-Type text/x-shellscript;
        add_header Content-Disposition 'attachment; filename="cove-dns-setup.sh"';
    }

    location ~ ^/config/dns/(macos|linux|windows|ios|android)$ {
        alias /etc/nginx/config/dns/$1;
        add_header Content-Type text/x-shellscript;
        add_header Content-Disposition 'attachment; filename="cove-dns-setup.sh"';
    }

    location = /dns-query {
        proxy_pass http://dnsmasq:8053;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location / {
        proxy_pass http://vault_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}

# pages subdomain — *.pages.cove
server {
    listen 443 ssl;
    server_name ~^(?<owner>[a-zA-Z0-9-]+)\.pages\.cove$;

    ssl_certificate     /certs/cove.local.pem;
    ssl_certificate_key /certs/cove.local-key.pem;

    root /data/pages/sites/$owner;

    location / {
        try_files /.index$uri /.index$uri/index.html $uri $uri/index.html =404;
    }

    location = /_health {
        access_log off;
        return 200 "healthy\n";
        add_header Content-Type text/plain;
    }
}{% if ts_dns_name is defined %}

# tailscale FQDN — tailscale cert TLS
server {
    listen 443 ssl;
    server_name {{ ts_dns_name }};

    ssl_certificate     /certs/fullchain.pem;
    ssl_certificate_key /certs/privkey.pem;

    location / {
        proxy_pass http://forgejo_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
{% endif %}
```

- [ ] **Step 2: Verify template renders with required variables**

Run: `python3 -c "from jinja2 import Template; t = Template(open('compose/nginx/default.conf.j2').read()); print(t.render(ts_dns_name='mbpbk-202602.taila90e7.ts.net'))"`
Expected: Output contains all server blocks, no Jinja2 errors

- [ ] **Step 3: Verify nginx config is valid**

Run: `docker run --rm -v $(pwd)/compose/nginx/default.conf.j2:/tmp/test.conf.j2:ro alpine:3.21 sh -c 'apk add --no-cache python3 py3-jinja2 && python3 -c "from jinja2 import Template; t=Template(open(\"/tmp/test.conf.j2\").read()); open(\"/tmp/rendered.conf\",\"w\").write(t.render(ts_dns_name=\"test.ts.net\"))" && apk add --no-cache nginx && nginx -t -c /tmp/rendered.conf 2>&1 || true'`
Expected: nginx reports syntax is OK (may warn about missing cert files — that's fine)

- [ ] **Step 4: Commit**

```bash
git add compose/nginx/default.conf.j2
git commit -m "feat: nginx config — /config/* endpoints, per-machine regex blocks, user.d include, DoH proxy"
```

---

## Chunk 3: nginx — Config Templates (HTML + DNS Scripts)

### Task 3.1: Create config.html.j2 info page template

**Files:**
- Create: `compose/nginx/config.html.j2`

- [ ] **Step 1: Write template**

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
    <li><a href="/config/dns/ios">/config/dns/ios</a> — iOS CA + DNS profile</li>
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

- [ ] **Step 2: Verify template renders**

Run: `python3 -c "from jinja2 import Template; t = Template(open('compose/nginx/config.html.j2').read()); print(t.render(ansible_hostname='mbpbk', ts_ip='100.64.0.5'))"`
Expected: Valid HTML with `mbpbk` and `100.64.0.5` substituted

- [ ] **Step 3: Commit**

```bash
git add compose/nginx/config.html.j2
git commit -m "feat: /config/ info page template"
```

### Task 3.2: Create DNS config script templates

**Files:**
- Create: `compose/nginx/config/dns/macos.j2`
- Create: `compose/nginx/config/dns/linux.j2`
- Create: `compose/nginx/config/dns/windows.j2`
- Create: `compose/nginx/config/dns/ios.j2`
- Create: `compose/nginx/config/dns/android.j2`
- Create: `compose/nginx/config/dns/unknown.j2`

- [ ] **Step 1: Write macos.j2**

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

- [ ] **Step 2: Write linux.j2**

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

- [ ] **Step 3: Write windows.j2**

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

- [ ] **Step 4: Write ios.j2**

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

- [ ] **Step 5: Write android.j2**

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

   Alternative (DoH app): install Intra, Nebulo, or DNSChanger.
   Point at: https://{{ ts_ip }}:8443/dns-query

   Manual alternative (per Wi-Fi network only):
   Settings → Wi-Fi → [your network] → gear icon →
   Advanced → Private DNS → Off
   Then: IP settings → Static → DNS 1: {{ ts_ip }}

3. Access Cove:
   https://<tailscale-fqdn>/ — Forgejo
   https://<tailscale-fqdn>/config/ — this page
```

- [ ] **Step 6: Write unknown.j2**

```
Cove on {{ ansible_hostname }}
===============================

Your platform was not auto-detected. Choose your OS:

macOS:
  curl /config/dns/macos | sudo bash

Linux:
  curl /config/dns/linux | sudo bash

Windows (admin PowerShell):
  irm /config/dns/windows | iex

iOS:
  Open /config/dns/ios in Safari → Install Profile

Android:
  See /config/dns/android for manual instructions

DNS IP: {{ ts_ip }} (Tailscale)
```

- [ ] **Step 7: Verify all templates render**

Run:
```bash
for t in macos linux windows ios android unknown; do
  python3 -c "from jinja2 import Template; t = Template(open('compose/nginx/config/dns/${t}.j2').read()); print(t.render(ansible_hostname='mbpbk', ts_ip='100.64.0.5', root_ca_b64='dGVzdA==', ca_uuid='11111111-1111-1111-1111-111111111111', dns_uuid='22222222-2222-2222-2222-222222222222', profile_uuid='33333333-3333-3333-3333-333333333333'))" && echo "--- $t OK ---"
done
```
Expected: Each template renders without Jinja2 errors

- [ ] **Step 8: Commit**

```bash
git add compose/nginx/config/dns/
git commit -m "feat: DNS config scripts — macos, linux, windows, ios, android, unknown"
```

---

## Chunk 4: Compose Integration — Volumes, Ansible, Certs

### Task 4.1: Update docker-compose.yml

**Files:**
- Modify: `compose/docker-compose.yml`

- [ ] **Step 1: Add nginx volume mounts**

Add four new volume mounts to the nginx service (after the existing pages/sites mount):

```yaml
      - ${COVE_DATA_ROOT}/nginx/user.d:/etc/nginx/user.d:ro
      - ${COVE_DATA_ROOT}/nginx/config.html:/etc/nginx/config.html:ro
      - ${COVE_DATA_ROOT}/nginx/config/dns:/etc/nginx/config/dns:ro
      - ${MKCERT_CAROOT}/rootCA.pem:/certs/rootCA.pem:ro
```

- [ ] **Step 2: Verify compose config is valid**

Run: `docker compose -f compose/docker-compose.yml config --no-interpolate 2>&1 | head -5`
Expected: No errors (may warn about missing .env vars — that's fine)

- [ ] **Step 3: Commit**

```bash
git add compose/docker-compose.yml
git commit -m "feat: nginx volume mounts — user.d, config.html, config/dns, rootCA.pem"
```

### Task 4.2: Update bringup.yml

**Files:**
- Modify: `compose/bringup.yml`

- [ ] **Step 1: Add ts_ip extraction (after tailscale DNS name task, ~line 43)**

```yaml
    - name: Get tailscale IP
      when: ts_status.rc == 0
      ansible.builtin.set_fact:
        ts_ip: "{{ (ts_status.stdout | from_json).Self.TailscaleIPs[0] }}"

    - name: Fallback to LAN IP when tailscale is down
      when: ts_status.rc != 0
      ansible.builtin.set_fact:
        ts_ip: "{{ ansible_default_ipv4.address }}"
```

- [ ] **Step 2: Add CAROOT detection (after mkcert install task, ~line 68)**

```yaml
    - name: Detect mkcert CAROOT path
      ansible.builtin.command: mkcert -CAROOT
      register: mkcert_caroot
      changed_when: false

    - name: Set MKCERT_CAROOT fact
      ansible.builtin.set_fact:
        mkcert_caroot_path: "{{ mkcert_caroot.stdout }}"
```

- [ ] **Step 3: Add root CA encoding + UUID generation (after CAROOT detection)**

```yaml
    - name: Read root CA certificate
      ansible.builtin.slurp:
        src: "{{ mkcert_caroot_path }}/rootCA.pem"
      register: root_ca_slurp

    - name: Base64-encode root CA (strip PEM headers for .mobileconfig)
      ansible.builtin.set_fact:
        root_ca_b64: "{{ (root_ca_slurp.content | b64decode | regex_replace('-----BEGIN CERTIFICATE-----\\n?', '') | regex_replace('-----END CERTIFICATE-----\\n?', '') | regex_replace('\\n', '') | trim) }}"

    - name: Generate UUIDs for iOS profile
      ansible.builtin.shell: python3 -c "import uuid; print(uuid.uuid4())"
      register: uuid1
      changed_when: false

    - name: Generate second UUID
      ansible.builtin.shell: python3 -c "import uuid; print(uuid.uuid4())"
      register: uuid2
      changed_when: false

    - name: Generate third UUID
      ansible.builtin.shell: python3 -c "import uuid; print(uuid.uuid4())"
      register: uuid3
      changed_when: false

    - name: Set UUID facts
      ansible.builtin.set_fact:
        ca_uuid: "{{ uuid1.stdout }}"
        dns_uuid: "{{ uuid2.stdout }}"
        profile_uuid: "{{ uuid3.stdout }}"
```

- [ ] **Step 4: Update mkcert cert SAN list (modify existing task ~line 70)**

Add `"*.cove"`, `"*.cove.{{ ansible_hostname }}"`, and `ca.cove` to the SAN list. The current cert has `cove` (bare) which does NOT act as a wildcard — `"*.cove"` must be explicit.

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
          - "*.cove.{{ ansible_hostname }}"
          - cove
          - git.cove
          - vault.cove
          - hc.cove
          - ca.cove
          - "*.pages.cove"
          - localhost
          - 127.0.0.1
          - "::1"
      args:
        creates: "{{ cove_data_root }}/certs/cove.local.pem"
      when: mkcert_check.rc == 0
```

- [ ] **Step 5: Update cert validation task (modify existing task ~line 90)**

Add `ca.cove`, `*.cove`, and `*.cove.{{ ansible_hostname }}` to the validation loop:

```yaml
    - name: Validate TLS cert covers required hostnames
      ansible.builtin.shell: |
        set -eo pipefail
        CERT="{{ cove_data_root }}/certs/cove.local.pem"
        for host in "git.cove" "vault.cove" "hc.cove" "ca.cove" "*.cove" "*.cove.{{ ansible_hostname }}"; do
          if ! openssl x509 -in "$CERT" -text -noout | grep -q "DNS:$host"; then
            echo "MISSING: $host"
            exit 1
          fi
        done
        echo "OK"
      register: cert_check
      changed_when: false
```

- [ ] **Step 6: Add ca.cove to /etc/hosts (modify existing task ~line 104)**

```yaml
    - name: Add *.cove hostnames to /etc/hosts
      become: true
      ansible.builtin.lineinfile:
        path: /etc/hosts
        regexp: '^127\.0\.0\.1\s+.*cove(\s|$)'
        line: "127.0.0.1 cove git.cove vault.cove hc.cove ca.cove"
        state: present
      failed_when: false
```

- [ ] **Step 7: Add data directories (modify existing task ~line 130)**

Add to the loop:
```yaml
        - "{{ cove_data_root }}/nginx/user.d"
        - "{{ cove_data_root }}/nginx/config/dns"
```

- [ ] **Step 8: Add template rendering tasks (after existing template tasks ~line 157)**

```yaml
    - name: Render nginx config info page
      ansible.builtin.template:
        src: "{{ nginx_conf_dir }}/config.html.j2"
        dest: "{{ cove_data_root }}/nginx/config.html"
        mode: "0644"

    - name: Render DNS config scripts
      ansible.builtin.template:
        src: "{{ nginx_conf_dir }}/config/dns/{{ item }}.j2"
        dest: "{{ cove_data_root }}/nginx/config/dns/{{ item }}"
        mode: "0644"
      loop:
        - macos
        - linux
        - windows
        - ios
        - android
        - unknown
```

- [ ] **Step 9: Add MKCERT_CAROOT to .env rendering (modify existing task ~line 160)**

Add to the `.env` content block:
```
          MKCERT_CAROOT={{ mkcert_caroot_path }}
```

- [ ] **Step 10: Update summary message (modify existing task ~line 235)**

Add bootstrap URL to the summary:
```
          Bootstrap new devices: http://{{ ansible_default_ipv4.address }}:8080/config/
          {% if ts_status.rc == 0 %}or https://{{ ts_ip }}:8443/config/{% endif %}
```

- [ ] **Step 11: Commit**

```bash
git add compose/bringup.yml
git commit -m "feat: bringup.yml — ts_ip, CAROOT, root CA encoding, UUIDs, cert SANs, data dirs, template rendering, bootstrap URL"
```

### Task 4.3: Update .env.example

**Files:**
- Modify: `compose/.env.example`

- [ ] **Step 1: Add MKCERT_CAROOT**

Add after the existing DNSMASQ_PORT line:
```
MKCERT_CAROOT=<from mkcert -CAROOT>
```

- [ ] **Step 2: Commit**

```bash
git add compose/.env.example
git commit -m "feat: MKCERT_CAROOT in .env.example"
```

---

## Chunk 5: Verification

### Task 5.1: Compose config validation

- [ ] **Step 1: Validate compose file structure**

Run: `docker compose -f compose/docker-compose.yml config --no-interpolate 2>&1`
Expected: No YAML errors, services listed (may warn about missing .env vars)

- [ ] **Step 2: Verify dnsmasq image builds**

Run: `docker build -t cove-dnsmasq-test compose/dnsmasq/ 2>&1`
Expected: Build succeeds, both dnsmasq and doh-proxy in image

- [ ] **Step 3: Verify dnsmasq image runs both processes**

Run: `docker run --rm cove-dnsmasq-test sh -c 'sleep 2 && ps aux' 2>&1`
Expected: Both `dnsmasq` and `doh-proxy` processes visible

### Task 5.2: Template rendering verification

- [ ] **Step 1: Verify all nginx templates render**

Run:
```bash
python3 -c "
from jinja2 import Template
import os
# default.conf.j2
t = Template(open('compose/nginx/default.conf.j2').read())
r = t.render(ts_dns_name='test.ts.net')
assert 'config_dns_type' in r
assert 'user.d' in r
assert 'return 444' in r
assert 'dns-query' in r
assert 'git\.cove\.[a-zA-Z0-9-]+' in r
assert 'vault\.cove\.[a-zA-Z0-9-]+' in r
print('default.conf.j2 OK')
# config.html.j2
t = Template(open('compose/nginx/config.html.j2').read())
r = t.render(ansible_hostname='test', ts_ip='1.2.3.4')
assert 'Cove on test' in r
assert '1.2.3.4' in r
print('config.html.j2 OK')
# dns scripts
for name in ['macos','linux','windows','ios','android','unknown']:
    t = Template(open(f'compose/nginx/config/dns/{name}.j2').read())
    r = t.render(ansible_hostname='test', ts_ip='1.2.3.4', root_ca_b64='dGVzdA==', ca_uuid='a', dns_uuid='b', profile_uuid='c')
    assert len(r) > 0
    print(f'config/dns/{name}.j2 OK')
print('All templates render successfully')
"
```
Expected: All templates render, no assertion errors

- [ ] **Step 2: Verify dnsmasq template renders**

Run: `python3 -c "from jinja2 import Template; t = Template(open('compose/dnsmasq/cove.conf.j2').read()); r = t.render(ansible_hostname='mbpbk', ts_ip='100.64.0.5'); assert 'address=/cove/127.0.0.1' in r; assert 'address=/cove.mbpbk/100.64.0.5' in r; print('OK')"`
Expected: OK

### Task 5.3: CLI tests

- [ ] **Step 1: Run full test suite**

Run: `uv run --directory cli pytest cli/tests/ -v`
Expected: All 66+ tests pass

### Task 5.4: Final commit

- [ ] **Step 1: Commit verification results**

```bash
git add -A
git diff --cached --stat
git commit -m "verify: all templates render, compose config valid, CLI tests pass"
```
