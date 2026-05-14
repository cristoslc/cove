---
title: "Cove Pages — Static Site Hosting"
created: 2026-05-09
authored-by: deepseek-v4-pro:cloud
status: Proposed
scope: MVP (Docker Compose)
trove: forgejo-static-pages@7612a9d
---

# Cove Pages — Static Site Hosting

Add GitHub Pages-compatible static site hosting to Cove. Three Forgejo composite actions replicate the `configure-pages`, `upload-pages-artifact`, and `deploy-pages` interface. An nginx reverse proxy serves static content with subdomain routing. All URLs are namespaced under `cove.` to avoid conflicts with other services on the MagicDNS name. The pipeline runs fully offline via dnsmasq for local wildcard DNS resolution and Tailscale certs for valid TLS in both modes.

## Target Audience

Solo developer running Cove on a MacBook Pro who wants to deploy static sites (Hugo, Zola, plain HTML) to a URL accessible from their phone on Tailscale and from the local machine offline.

## DNS Model

**`cove.` namespace.** All Cove services live under the MagicDNS name with a `cove.` prefix, isolating them from other apps that might use the same machine's hostname:

| Service | URL |
|---------|-----|
| Forgejo | `https://git.cove.mbpbk-202602.taila90e7.ts.net` |
| Pages (wildcard) | `https://<owner>.pages.cove.mbpbk-202602.taila90e7.ts.net` |

MagicDNS natively resolves subdomains to the same machine, so `*.cove.mbpbk-202602.taila90e7.ts.net` all route to the Mac.

**Offline wildcard DNS.** macOS `/etc/hosts` does not support wildcards. A dnsmasq container runs in the Docker Compose stack, configured to resolve `*.cove.mbpbk-202602.taila90e7.ts.net` → `127.0.0.1`. macOS is pointed at dnsmasq for this domain via `/etc/resolver/` — the standard macOS mechanism for per-domain DNS forwarding. This replicates the same wildcard DNS pattern that GitHub Pages uses with `*.github.io`, resolved locally instead of by an authoritative server.

Online, MagicDNS takes priority (dnsmasq is not in the resolution path). Offline, dnsmasq handles the wildcard and `/etc/resolver/cove.mbpbk-202602.taila90e7.ts.net` routes the domain to it. The user sees the same FQDN in both modes.

**No `.cove.local` in this MVP.** That namespace is reserved for the future k3s migration and may coexist with Tailscale access later.

## Architecture

```
                        Tailscale Serve
                             │
                    ┌────────▼────────┐
                    │     nginx       │  127.0.0.1:443 (TLS)
                    │  (new service)  │
                    └──┬──────────┬───┘
                       │          │
    Host: git.cove... │          │  Host: *.pages.cove...
                       ▼          ▼
                   Forgejo    /data/pages/sites/
                   (:3000)    (bind mount)
```

**nginx** joins `docker-compose.yml` as the unified reverse proxy. It terminates TLS on port 443 using Tailscale certs (`fullchain.pem`, `privkey.pem`), which are valid for the MagicDNS FQDN and work offline since they are locally cached. nginx also listens on port 80 to redirect HTTP to HTTPS.

It inspects the `Host` header and routes:
- `git.cove.mbpbk-202602.taila90e7.ts.net` → Forgejo on port 3000.
- `*.pages.cove.mbpbk-202602.taila90e7.ts.net` → static files from `/data/pages/sites/`.

The pages directory structure mirrors the URL path: `/data/pages/sites/<owner>/<repo>/index.html` is served at `https://<owner>.pages.cove.<ts.net>/<repo>/`. An nginx `try_files` rule handles directory indexes and clean URLs.

**Forgejo and Vault** keep their internal ports (3000, 8200) but no longer publish host ports. nginx owns 443 (and 80 for redirect). Vault is accessed directly on `127.0.0.1:8200` by the CLI — it does not go through nginx.

**dnsmasq** runs alongside nginx. It is configured to answer only for `*.cove.mbpbk-202602.taila90e7.ts.net` → `127.0.0.1`. macOS forwards queries for this domain to dnsmasq via `/etc/resolver/`. dnsmasq does not interfere with MagicDNS or any other DNS resolution.

**Tailscale Serve** is reconfigured to point at nginx:443. The command becomes `tailscale serve --bg https://localhost:443`.

## Actions

Three shell-based composite actions provisioned as Forgejo repositories. They accept the same inputs and produce the same outputs as the GitHub Pages action suite.

### configure-pages

Repository: `cove/configure-pages`

```yaml
inputs:
  static_site_generator:
    description: "SSG to configure (hugo, jekyll, zola, next, or leave empty to auto-detect)"
    required: false
    default: ""
  token:
    description: "GitHub token (ignored in Cove, accepted for compatibility)"
    required: false
    default: ""
outputs:
  base_url:
    description: "Base URL for the site"
  origin:
    description: "Site origin"
  host:
    description: "Site hostname"
  base_path:
    description: "Base path for the site"
  pages_url:
    description: "Full URL where the site will be served"
```

Behavior:
1. Determine the owner and repository name from `GITHUB_REPOSITORY` (which Forgejo Actions sets identically).
2. Detect the SSG by probing known config files in the workspace — `config.toml` / `config.yaml` / `config.json` → Hugo, `_config.yml` → Jekyll, `zola.toml` → Zola, etc. Use the explicit `static_site_generator` input if provided.
3. Set `host` to `<owner>.pages.cove.mbpbk-202602.taila90e7.ts.net`.
4. Set `base_path` to `/<repo>` unless the repository is named `pages` (user/org site), in which case `base_path` is `/`.
5. Set `origin` to `https://<host>`.
6. Set `base_url` to `<origin><base_path>`.
7. Set `pages_url` to `<base_url>`.
8. Write all outputs to `GITHUB_OUTPUT` and `GITHUB_ENV` so subsequent steps can reference them.

### upload-pages-artifact

Repository: `cove/upload-pages-artifact`

```yaml
inputs:
  path:
    description: "Directory containing static site output"
    required: false
    default: "_site/"
  name:
    description: "Artifact name (used as annotation only in Cove)"
    required: false
    default: "github-pages"
outputs:
  artifact_id:
    description: "Identifier for the uploaded artifact"
```

Behavior:
1. Verify `path` exists and contains files. Fail if empty.
2. Create a tar.gz archive of `path`.
3. Determine `artifact_id` from context: `<owner>/<repo>/<run-id>`.
4. Push the tar.gz to the `cove/pages-artifacts` repository under the path `artifacts/<owner>/<repo>/<run-id>.tar.gz` using a Forgejo API token (read from `GITHUB_TOKEN`, which Forgejo sets to the runner's job token) and the Forgejo repository API.
5. Output the `artifact_id`.
6. Emit a log line with the artifact path for the audit trail.

### deploy-pages

Repository: `cove/deploy-pages`

```yaml
inputs:
  artifact_id:
    description: "Artifact identifier from upload-pages-artifact"
    required: true
  owner:
    description: "Repository owner"
    required: true
  repo:
    description: "Repository name"
    required: true
outputs:
  page_url:
    description: "URL where the site is served"
  alive:
    description: "'true' if deployment succeeded"
```

Behavior:
1. Derive the host from configuration or fall back to `<owner>.pages.cove.mbpbk-202602.taila90e7.ts.net`.
2. Fetch the tar.gz from the `cove/pages-artifacts` repository using the Forgejo API.
3. Determine the target path: the index site path is `sites/<owner>/.index/`, and a project site path is `sites/<owner>/<repo>/`.
4. Extract the archive into `/data/pages/sites/<path>/` on the nginx container. If the target exists, atomically replace it (`mv` old, extract new, `rm` old on success).
5. Signal nginx to reload: run `nginx -s reload` via `docker exec cove-nginx`.
6. Set `page_url` to `https://<owner>.pages.cove.mbpbk-202602.taila90e7.ts.net/<repo>` (or omit `<repo>` for the index site).
7. Set `alive` to `true`.
8. Write all outputs to `GITHUB_OUTPUT`.

## Nginx Configuration

```nginx
# HTTP → HTTPS redirect
server {
    listen 80;
    server_name git.cove.mbpbk-202602.taila90e7.ts.net ~^.+\.pages\.cove\..+$;
    return 301 https://$host$request_uri;
}

# Forgejo (HTTPS)
server {
    listen 443 ssl;
    server_name git.cove.mbpbk-202602.taila90e7.ts.net;

    ssl_certificate     /certs/fullchain.pem;
    ssl_certificate_key /certs/privkey.pem;

    location / {
        proxy_pass http://forgejo:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}

# Static pages (HTTPS)
server {
    listen 443 ssl;
    server_name ~^.+\.pages\.cove\..+$;

    ssl_certificate     /certs/fullchain.pem;
    ssl_certificate_key /certs/privkey.pem;

    root /data/pages/sites;

    set $owner_path "";
    if ($host ~ "^([^.]+)\.pages\.") {
        set $owner_path "/$1";
    }

    location / {
        try_files $owner_path/.index$uri $owner_path/.index$uri/index.html $owner_path$uri $owner_path$uri/index.html =404;
    }
}
```

The Tailscale cert covers the MagicDNS name and all subdomains. The `if` in nginx is safe here — it runs once per request during the rewrite phase to extract the owner subdomain and contains no redirects or rewrites.

## dnsmasq Configuration

```
# /etc/dnsmasq.d/cove.conf (provided to dnsmasq container as a bind mount or config)
address=/cove.mbpbk-202602.taila90e7.ts.net/127.0.0.1
bind-interfaces
listen-address=127.0.0.1
```

The `address=` directive is a wildcard — it resolves any label under `cove.mbpbk-202602.taila90e7.ts.net` to `127.0.0.1`. This includes `git.cove.*`, `*.pages.cove.*`, and any future subdomains.

The macOS resolver configuration at `/etc/resolver/cove.mbpbk-202602.taila90e7.ts.net`:

```
nameserver 127.0.0.1
port 5353
```

This tells macOS to forward DNS queries for this domain to the dnsmasq container on port 5353 (dnsmasq runs on an alternate port since macOS has its own resolver on 53).

## Provisioning

A new Ansible playbook `provision_pages.yml` runs after nginx and dnsmasq are healthy. It:

1. Verifies the `cove` organization exists in Forgejo (the existing `provision_forgejo.yml` creates it).
2. Creates four repositories under the `cove` org: `configure-pages`, `upload-pages-artifact`, `deploy-pages`, and `pages-artifacts`.
3. Pushes the action code (a single `action.yml` per repo) plus a minimal `README.md` to each.
4. Generates and pushes a workflow file `.forgejo/workflows/pages-template.yml` to Cove's own repo as a reference, showing the three actions wired together.
5. Creates a Forgejo API token for the actions to authenticate with the artifact store.

## Data Layout

```
~/Documents/cove-data/
  pages/
    sites/
      <owner>/
        .index/              ← user/org site (repo named "pages")
          index.html
          assets/
        <repo>/              ← per-repository site
          index.html
          assets/
  nginx/
    conf.d/
      default.conf           ← rendered from template
  dnsmasq/
    cove.conf                ← wildcard domain resolution
```

## Workflow Template

Each project's `.forgejo/workflows/pages.yml`:

```yaml
on:
  push:
    branches: [pages]

jobs:
  build-and-deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Configure Pages
        uses: http://forgejo/cove/configure-pages@main
        id: pages

      - name: Build
        run: hugo --minify --baseURL "${{ steps.pages.outputs.base_url }}"

      - name: Upload artifact
        uses: http://forgejo/cove/upload-pages-artifact@main
        with:
          path: public/

      - name: Deploy
        uses: http://forgejo/cove/deploy-pages@main
        with:
          artifact_id: ${{ steps.upload.outputs.artifact_id }}
          owner: ${{ github.repository_owner }}
          repo: ${{ github.event.repository.name }}
```

The `uses:` URL uses the Docker-internal hostname `forgejo` (the Compose service name), since the Actions runner container is on the same Docker network. No external DNS resolution needed.

## Compatibility Mapping

| GitHub Action | Cove Action | Change Required |
|---------------|-------------|-----------------|
| `actions/configure-pages@v4` | `http://forgejo/cove/configure-pages@main` | `uses:` line only |
| `actions/upload-pages-artifact@v3` | `http://forgejo/cove/upload-pages-artifact@main` | `uses:` line only |
| `actions/deploy-pages@v4` | `http://forgejo/cove/deploy-pages@main` | `uses:` line only |

All `with:` blocks and outputs are compatible.

## Offline Behavior

1. `/etc/resolver/cove.mbpbk-202602.taila90e7.ts.net` routes `.cove.*.ts.net` DNS queries to the dnsmasq container.
2. dnsmasq resolves the wildcard domain to `127.0.0.1`.
3. nginx receives requests at `127.0.0.1:443` with valid TLS using Tailscale certs, which are locally cached and do not require external CA connectivity. Browsers accept them offline without warnings.
4. Host-based routing works identically to the online case.
5. Forgejo Actions runners are local Docker containers on the same network. The actions call Forgejo's API on `http://forgejo:3000` (internal Docker network, always reachable) and `nginx -s reload` via `docker exec`. No external API calls.
6. Offline, `magicdns.localhost-tailscale-daemon` (or whatever MagicDNS resolves to online) is not queried. The dnsmasq resolver takes precedence per macOS resolver configuration.

## Non-Goals for MVP

- k3s-based deployment (`.cove.local` namespace, Helm charts, Kubernetes manifests — will come later).
- Custom domains in the `.domains` / DNS TXT record style.
- Private pages with OAuth2 access control.
- The `_redirects`/`_headers` file conventions (can be added later).
- A `cove pages` CLI subcommand (provisioning is Ansible-only).

## Acceptance Criteria

1. `docker compose up` starts Forgejo, Vault, nginx, and dnsmasq. Forgejo is reachable at `https://git.cove.mbpbk-202602.taila90e7.ts.net` (online via Tailscale Serve, offline via dnsmasq), with valid TLS in both modes.
2. The three Cove actions repos (`cove/configure-pages`, `cove/upload-pages-artifact`, `cove/deploy-pages`) and the artifact store (`cove/pages-artifacts`) exist in Forgejo after provisioning.
3. A push to the `pages` branch of any repo with a workflow using the three Cove actions builds and deploys a static site.
4. The deployed site is served at `https://<owner>.pages.cove.mbpbk-202602.taila90e7.ts.net/<repo>` from a phone on Tailscale.
5. The same URL works offline from the Mac with dnsmasq configured, at `https://<owner>.pages.cove.mbpbk-202602.taila90e7.ts.net/<repo>`, with valid TLS (no warnings).
6. The `cove.` namespace does not interfere with other services using the machine's MagicDNS hostname.
7. An example project can be deployed through the full pipeline.
