# Cove Pages — Static Site Hosting Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add GitHub Pages-compatible static site hosting to Cove with an nginx reverse proxy, dnsmasq offline DNS, and three Forgejo composite actions.

**Architecture:** nginx joins docker-compose.yml as the TLS-terminating reverse proxy on `127.0.0.1:443`, routing `git.cove.{ts.net}` to Forgejo:3000 and `*.pages.cove.{ts.net}` to static files served directly from disk. dnsmasq provides offline wildcard DNS. A new `provision_pages.yml` Ansible playbook seeds four repos into Forgejo. The deploy action writes files to the pages data directory — nginx picks them up without a reload since no file cache is configured.

**Tech Stack:** Docker Compose, Forgejo, nginx:1.27-alpine, Alpine 3.21 + dnsmasq, Ansible, shell composite actions, Tailscale certs.

**Note:** nginx currently owns port 443 directly. The future k3s track should run a general-purpose ingress controller (Traefik) that can route to Cove services alongside any other services the user runs. This compose nginx is an MVP placeholder for that role.

**Spec:** `docs/superpowers/specs/2026-05-09-cove-pages-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `compose/group_vars/all.yml` | Modify | Add nginx, dnsmasq, pages variables |
| `compose/nginx/default.conf` | Create | TLS termination + host-header routing + static file serving |
| `compose/dnsmasq/cove.conf` | Create | `address=/cove.*.ts.net/127.0.0.1` wildcard |
| `compose/dnsmasq/Dockerfile` | Create | Alpine + dnsmasq container |
| `compose/docker-compose.yml` | Modify | Add nginx and dnsmasq services; switch forgejo to HTTP behind proxy |
| `compose/bringup.yml` | Modify | New data dirs, .env vars, forgejo ROOT_URL via proxy, TS serve → 443, nginx health check |
| `compose/files/actions/configure-pages/action.yml` | Create | SSG detection + URL config outputs |
| `compose/files/actions/upload-pages-artifact/action.yml` | Create | Tar + git-push to artifact store |
| `compose/files/actions/deploy-pages/action.yml` | Create | Fetch artifact, extract to pages root (no reload needed) |
| `compose/files/actions/pages-template.yml` | Create | Reference workflow |
| `compose/provision_pages.yml` | Create | Idempotent org + repos + action code provisioning |

---

## Chunk 1: Infrastructure

### Task 1: Add nginx, dnsmasq, pages group vars

**Files:**
- Modify: `compose/group_vars/all.yml`

- [ ] **Step 1: Append new vars**

After `pod_pull_policy: missing`, add:

```yaml
# --- Pages ---
pages_data_root: "{{ cove_data_root }}/pages"

# --- nginx ---
nginx_image: "nginx:1.27-alpine"
nginx_container_name: cove-nginx
nginx_conf_dir: "{{ playbook_dir }}/nginx"
nginx_http_bind: "127.0.0.1"
nginx_http_port: 80
nginx_https_port: 443

# --- dnsmasq ---
dnsmasq_conf_dir: "{{ playbook_dir }}/dnsmasq"
dnsmasq_container_name: cove-dnsmasq
dnsmasq_bind: "127.0.0.1"
dnsmasq_port: 5353
```

- [ ] **Step 2: Commit**

```bash
git add compose/group_vars/all.yml
git commit -m "feat(pages): add nginx, dnsmasq, pages group vars"
```

### Task 2: Create nginx config

**Files:**
- Create: `compose/nginx/default.conf`

- [ ] **Step 1: Write config**

```bash
mkdir -p compose/nginx
```

```nginx
server {
    listen 80;
    server_name git.cove.mbpbk-202602.taila90e7.ts.net ~^.+\.pages\.cove\..+$;
    return 301 https://$host$request_uri;
}

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

- [ ] **Step 2: Commit**

```bash
git add compose/nginx/default.conf
git commit -m "feat(pages): add nginx reverse proxy config with pages subdomain routing"
```

### Task 3: Create dnsmasq config and Dockerfile

**Files:**
- Create: `compose/dnsmasq/cove.conf`
- Create: `compose/dnsmasq/Dockerfile`

- [ ] **Step 1: Write both files**

```bash
mkdir -p compose/dnsmasq
```

`compose/dnsmasq/cove.conf`:

```
address=/cove.mbpbk-202602.taila90e7.ts.net/127.0.0.1
bind-interfaces
listen-address=0.0.0.0
port=5353
no-hosts
no-resolv
```

`compose/dnsmasq/Dockerfile`:

```dockerfile
FROM alpine:3.21
RUN apk add --no-cache dnsmasq
COPY cove.conf /etc/dnsmasq.d/cove.conf
ENTRYPOINT ["dnsmasq", "--no-daemon", "--conf-dir=/etc/dnsmasq.d"]
```

- [ ] **Step 2: Commit**

```bash
git add compose/dnsmasq/
git commit -m "feat(pages): add dnsmasq config and Dockerfile for offline wildcard DNS"
```

### Task 4: Update docker-compose.yml

**Files:**
- Modify: `compose/docker-compose.yml`

- [ ] **Step 1: Remove forgejo HTTP port publish, cert volume, HTTPS config**

Edit the forgejo service block:

Remove:
```yaml
      - "${FORGEJO_HTTP_BIND:-127.0.0.1}:${FORGEJO_HTTP_PORT:-3000}:3000"
```

Remove the certs volume:
```yaml
      - ${FORGEJO_DATA_ROOT}/certs:/certs:ro
```

Replace the PROTOCOL/CERT/KEY lines:
```yaml
      FORGEJO__server__PROTOCOL: https
      FORGEJO__server__CERT_FILE: /certs/fullchain.pem
      FORGEJO__server__KEY_FILE: /certs/privkey.pem
      FORGEJO__server__HTTP_PORT: "3000"
```
With:
```yaml
      FORGEJO__server__PROTOCOL: http
      FORGEJO__server__HTTP_PORT: "3000"
```

The forgejo SSH port publish stays:
```yaml
      - "${FORGEJO_SSH_BIND:-127.0.0.1}:${FORGEJO_SSH_PORT:-2222}:22"
```

- [ ] **Step 2: Add nginx service**

Insert before `vault:`:

```yaml
  nginx:
    image: ${NGINX_IMAGE:-nginx:1.27-alpine}
    container_name: ${NGINX_CONTAINER_NAME:-cove-nginx}
    restart: unless-stopped
    depends_on:
      forgejo:
        condition: service_started
    volumes:
      - ${NGINX_CONF_DIR:-./nginx}/default.conf:/etc/nginx/conf.d/default.conf:ro
      - ${COVE_DATA_ROOT}/certs:/certs:ro
      - ${COVE_DATA_ROOT}/pages/sites:/data/pages/sites:ro
    ports:
      - "${NGINX_HTTP_BIND:-127.0.0.1}:${NGINX_HTTPS_PORT:-443}:443"
      - "${NGINX_HTTP_BIND:-127.0.0.1}:${NGINX_HTTP_PORT:-80}:80"
```

- [ ] **Step 3: Add dnsmasq service**

Insert after nginx, before vault:

```yaml
  dnsmasq:
    build: ${DNSMASQ_CONF_DIR:-./dnsmasq}
    container_name: ${DNSMASQ_CONTAINER_NAME:-cove-dnsmasq}
    restart: unless-stopped
    ports:
      - "${DNSMASQ_BIND:-127.0.0.1}:${DNSMASQ_PORT:-5353}:5353"
    cap_add:
      - NET_BIND_SERVICE
```

- [ ] **Step 4: Verify four services exist**

```bash
grep -c '^  [a-z]' compose/docker-compose.yml
```

Expected: `4`

- [ ] **Step 5: Commit**

```bash
git add compose/docker-compose.yml
git commit -m "feat(pages): add nginx proxy and dnsmasq to compose stack"
```

### Task 5: Update bringup.yml

**Files:**
- Modify: `compose/bringup.yml`

- [ ] **Step 1: Add data directories**

Append to the `Create cove data directories` loop:

```yaml
        - "{{ cove_data_root }}/pages/sites"
        - "{{ cove_data_root }}/nginx"
```

- [ ] **Step 2: Set forgejo ROOT_URL to proxy URL when Tailscale is online**

Replace the existing "Set Forgejo URLs to localhost" + "Use tailscale DNS name for Forgejo URLs" facts (lines 9-13 and 29-33) with a single block that sets the correct ROOT_URL:

```yaml
    - name: Set Forgejo URLs (localhost fallback)
      ansible.builtin.set_fact:
        forgejo_domain: localhost
        forgejo_root_url: "http://localhost:{{ forgejo_http_port }}/"
        forgejo_ssh_domain: localhost

    - name: Check if tailscale is up
      ansible.builtin.command: tailscale status --json
      register: ts_status
      changed_when: false
      failed_when: false
      no_log: true

    - name: Set up tailscale serve
      when: ts_status.rc == 0
      block:
        - name: Get tailscale DNS name
          ansible.builtin.set_fact:
            ts_dns_name: "{{ (ts_status.stdout | from_json).Self.DNSName | regex_replace('\\.$', '') }}"

        - name: Set forgejo URLs through nginx proxy
          ansible.builtin.set_fact:
            forgejo_domain: "git.cove.{{ ts_dns_name }}"
            forgejo_root_url: "https://git.cove.{{ ts_dns_name }}/"
            forgejo_ssh_domain: "{{ ts_dns_name }}"

        - name: Point tailscale FQDN to localhost in hosts file
          become: true
          ansible.builtin.lineinfile:
            path: /etc/hosts
            regexp: '^127\.0\.0\.1\s+{{ ts_dns_name | regex_escape }}(\s+.*)?$'
            line: "127.0.0.1 {{ ts_dns_name }}"
            state: present

        - name: Configure tailscale serve for HTTPS on port 443
          ansible.builtin.shell: |
            set -eo pipefail
            JSON=$(tailscale serve status --json 2>/dev/null || echo '{}')
            if echo "$JSON" | python3 -c "import json,sys; s=json.load(sys.stdin); exit(0 if s.get('Web',{}).get('443') else 1)"; then
              echo "already configured"
            else
              tailscale serve --bg --https "443" "https://127.0.0.1:443"
              echo "configured"
            fi
          register: ts_serve_https
          changed_when: "'configured' in ts_serve_https.stdout and 'already' not in ts_serve_https.stdout"
```

Explanation: When Tailscale is online, `forgejo_root_url` becomes `https://git.cove.{ts.net}/` so Forgejo generates correct links through the proxy. When offline, it falls back to `http://localhost:3000/` so Ansible can still reach it for provisioning.

- [ ] **Step 3: Add nginx/dnsmasq env vars to .env rendering**

Append to the `content:` block:

```
          NGINX_IMAGE={{ nginx_image }}
          NGINX_CONTAINER_NAME={{ nginx_container_name }}
          NGINX_CONF_DIR={{ nginx_conf_dir }}
          NGINX_HTTP_BIND={{ nginx_http_bind }}
          NGINX_HTTP_PORT={{ nginx_http_port }}
          NGINX_HTTPS_PORT={{ nginx_https_port }}
          DNSMASQ_CONF_DIR={{ dnsmasq_conf_dir }}
          DNSMASQ_CONTAINER_NAME={{ dnsmasq_container_name }}
          DNSMASQ_BIND={{ dnsmasq_bind }}
          DNSMASQ_PORT={{ dnsmasq_port }}
```

- [ ] **Step 4: Add nginx health check**

Insert after the "Wait for Forgejo health endpoint" task:

```yaml
    - name: Wait for nginx to respond
      ansible.builtin.uri:
        url: "http://127.0.0.1:{{ nginx_http_port }}"
        status_code: [200, 301, 302, 404]
      register: nginx_health
      retries: 20
      delay: 2
      until: nginx_health.status in [200, 301, 302, 404]
```

- [ ] **Step 5: Update summary**

Replace the `Print summary` debug msg:

```yaml
    - name: Print summary
      ansible.builtin.debug:
        msg: |
          Containers are up.
            Nginx  : https://127.0.0.1:{{ nginx_https_port }} (reverse proxy)
                     ├─ git.cove.{{ ts_dns_name | default('ts.net') }} → forgejo:3000
                     └─ *.pages.cove.{{ ts_dns_name | default('ts.net') }} → /data/pages/sites/
            Forgejo: {{ forgejo_root_url }} (behind nginx)
            SSH    : {{ forgejo_ssh_bind }}:{{ forgejo_ssh_port }}
            DNS    : dnsmasq on {{ dnsmasq_bind }}:{{ dnsmasq_port }} (offline wildcard)
            {% if ts_status.rc == 0 %}Tailscale: {{ ts_dns_name }} (serve → localhost:443 → nginx)
            {% endif %}Vault  : {{ vault_addr }} (initialized={{ vault_health.json.initialized | default(false) }}, sealed={{ vault_health.json.sealed | default(true) }})

          Next steps:
            1. ansible-playbook -i inventory.yml bootstrap_vault.yml
            2. ansible-playbook -i inventory.yml provision_vault_user.yml
            3. ansible-playbook -i inventory.yml provision_forgejo.yml
            4. ansible-playbook -i inventory.yml provision_pages.yml
```

- [ ] **Step 6: Commit**

```bash
git add compose/bringup.yml
git commit -m "feat(pages): wire proxy ROOT_URL, TS serve, nginx health check, and env vars"
```

---

## Chunk 2: Composite Actions

### Task 6: Create configure-pages action

**Files:**
- Create: `compose/files/actions/configure-pages/action.yml`

- [ ] **Step 1: Write the action**

```bash
mkdir -p compose/files/actions/configure-pages
```

```yaml
name: "Configure Pages"
description: "Configure GitHub Pages-compatible deployment for Cove"

inputs:
  static_site_generator:
    description: "SSG (hugo, jekyll, zola, or leave empty to auto-detect)"
    required: false
    default: ""
  token:
    description: "GitHub token (ignored, accepted for compatibility)"
    required: false
    default: ""

outputs:
  base_url:
    description: "Base URL for the site"
    value: "${{ steps.configure.outputs.base_url }}"
  origin:
    description: "Site origin"
    value: "${{ steps.configure.outputs.origin }}"
  host:
    description: "Site hostname"
    value: "${{ steps.configure.outputs.host }}"
  base_path:
    description: "Base path for the site"
    value: "${{ steps.configure.outputs.base_path }}"
  pages_url:
    description: "Full URL"
    value: "${{ steps.configure.outputs.pages_url }}"

runs:
  using: "composite"
  steps:
    - name: Configure
      id: configure
      shell: bash
      run: |
        set -euo pipefail
        REPO="${GITHUB_REPOSITORY##*/}"
        OWNER="${GITHUB_REPOSITORY%%/*}"

        SSG="${{ inputs.static_site_generator }}"
        if [ -z "$SSG" ]; then
          [ -f "config.toml" ] || [ -f "config.yaml" ] || [ -f "config.json" ] && SSG="hugo" || true
          [ -f "_config.yml" ] && SSG="jekyll" || true
          [ -f "zola.toml" ] && SSG="zola" || true
          [ -f "package.json" ] && SSG="next" || true
          SSG="${SSG:-none}"
        fi

        HOST="${OWNER}.pages.cove.mbpbk-202602.taila90e7.ts.net"
        ORIGIN="https://${HOST}"
        BASE_PATH="/"
        [ "$REPO" != "pages" ] && BASE_PATH="/${REPO}"
        BASE_URL="${ORIGIN}${BASE_PATH}"
        PAGES_URL="${BASE_URL}"

        echo "static_site_generator=${SSG}" >> "$GITHUB_OUTPUT"
        echo "host=${HOST}" >> "$GITHUB_OUTPUT"
        echo "origin=${ORIGIN}" >> "$GITHUB_OUTPUT"
        echo "base_path=${BASE_PATH}" >> "$GITHUB_OUTPUT"
        echo "base_url=${BASE_URL}" >> "$GITHUB_OUTPUT"
        echo "pages_url=${PAGES_URL}" >> "$GITHUB_OUTPUT"
        echo "PAGES_HOST=${HOST}" >> "$GITHUB_ENV"
        echo "PAGES_BASE_URL=${BASE_URL}" >> "$GITHUB_ENV"
        echo "configure-pages: host=${HOST} base_path=${BASE_PATH} ssg=${SSG}"
```

- [ ] **Step 2: Commit**

```bash
git add compose/files/actions/configure-pages/
git commit -m "feat(pages): add configure-pages composite action"
```

### Task 7: Create upload-pages-artifact action

**Files:**
- Create: `compose/files/actions/upload-pages-artifact/action.yml`

- [ ] **Step 1: Write the action**

```bash
mkdir -p compose/files/actions/upload-pages-artifact
```

```yaml
name: "Upload Pages Artifact"
description: "Upload static site artifact to Cove pages artifact store"

inputs:
  path:
    description: "Directory of static site output"
    required: false
    default: "_site/"
  name:
    description: "Artifact name (annotation only)"
    required: false
    default: "github-pages"

outputs:
  artifact_id:
    description: "Identifier for the uploaded artifact"
    value: "${{ steps.upload.outputs.artifact_id }}"

runs:
  using: "composite"
  steps:
    - name: Upload
      id: upload
      shell: bash
      run: |
        set -euo pipefail
        PATH_IN="${{ inputs.path }}"

        [ -d "$PATH_IN" ] || { echo "::error::Directory '$PATH_IN' not found"; exit 1; }
        [ -n "$(ls -A "$PATH_IN" 2>/dev/null)" ] || { echo "::error::Directory '$PATH_IN' empty"; exit 1; }

        OWNER="${GITHUB_REPOSITORY%%/*}"
        REPO="${GITHUB_REPOSITORY##*/}"
        RUN_ID="${GITHUB_RUN_ID:-local}"
        ARTIFACT_ID="${OWNER}/${REPO}/${RUN_ID}"
        REMOTE_PATH="artifacts/${OWNER}/${REPO}/${RUN_ID}.tar.gz"

        [ -n "${GITHUB_TOKEN:-}" ] || { echo "::error::GITHUB_TOKEN not set"; exit 1; }

        TMPDIR="$(mktemp -d)"
        trap 'rm -rf "$TMPDIR"' EXIT

        git clone --quiet \
          "http://oauth2:${GITHUB_TOKEN}@forgejo:3000/cove/pages-artifacts.git" \
          "$TMPDIR"

        cd "$TMPDIR"
        mkdir -p "$(dirname "$REMOTE_PATH")"
        tar -czf "$REMOTE_PATH" -C "$(dirname "$PATH_IN")" "$(basename "$PATH_IN")"

        git config user.email "cove-pages@cove.local"
        git config user.name "Cove Pages"
        git add "$REMOTE_PATH"
        git diff --cached --quiet && { echo "upload-pages-artifact: unchanged"; echo "artifact_id=${ARTIFACT_ID}" >> "$GITHUB_OUTPUT"; exit 0; }

        git commit -m "pages artifact: ${{ inputs.name }} (${ARTIFACT_ID})"
        git push origin main

        echo "artifact_id=${ARTIFACT_ID}" >> "$GITHUB_OUTPUT"
        echo "upload-pages-artifact: stored ${REMOTE_PATH}"
```

- [ ] **Step 2: Commit**

```bash
git add compose/files/actions/upload-pages-artifact/
git commit -m "feat(pages): add upload-pages-artifact composite action"
```

### Task 8: Create deploy-pages action

**Files:**
- Create: `compose/files/actions/deploy-pages/action.yml`

The deploy action writes files directly to the pages data directory. nginx serves them from disk with no file cache configured, so no reload is needed — changed files are picked up on the next request.

- [ ] **Step 1: Write the action**

```bash
mkdir -p compose/files/actions/deploy-pages
```

```yaml
name: "Deploy Pages"
description: "Deploy static site artifact to Cove pages server"

inputs:
  artifact_id:
    description: "Artifact identifier"
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
    value: "${{ steps.deploy.outputs.page_url }}"
  alive:
    description: "'true' if deployment succeeded"
    value: "${{ steps.deploy.outputs.alive }}"

runs:
  using: "composite"
  steps:
    - name: Deploy
      id: deploy
      shell: bash
      run: |
        set -euo pipefail
        ARTIFACT_ID="${{ inputs.artifact_id }}"
        OWNER="${{ inputs.owner }}"
        REPO="${{ inputs.repo }}"

        RUN_ID="${ARTIFACT_ID##*/}"
        REMOTE_PATH="artifacts/${OWNER}/${REPO}/${RUN_ID}.tar.gz"

        [ -n "${GITHUB_TOKEN:-}" ] || { echo "::error::GITHUB_TOKEN not set"; exit 1; }

        TMPDIR="$(mktemp -d)"
        trap 'rm -rf "$TMPDIR"' EXIT

        git clone --depth 1 --branch main --quiet \
          "http://oauth2:${GITHUB_TOKEN}@forgejo:3000/cove/pages-artifacts.git" \
          "$TMPDIR"

        [ -f "$TMPDIR/$REMOTE_PATH" ] || { echo "::error::Artifact not found: ${REMOTE_PATH}"; exit 1; }

        PAGES_ROOT="${PAGES_DATA_ROOT:-/data/pages}"
        [ "$REPO" = "pages" ] && SITE_PATH="sites/${OWNER}/.index" || SITE_PATH="sites/${OWNER}/${REPO}"
        DEST="${PAGES_ROOT}/${SITE_PATH}"

        [ "$REPO" = "pages" ] && PAGE_URL="https://${OWNER}.pages.cove.mbpbk-202602.taila90e7.ts.net" || \
          PAGE_URL="https://${OWNER}.pages.cove.mbpbk-202602.taila90e7.ts.net/${REPO}"

        mkdir -p "$(dirname "$DEST")"
        rm -rf "${DEST}.new" 2>/dev/null || true
        mkdir -p "${DEST}.new"

        tar -xzf "$TMPDIR/$REMOTE_PATH" -C "${DEST}.new" --strip-components=1

        [ -d "$DEST" ] && { mv "$DEST" "${DEST}.old" 2>/dev/null || true; }
        mv "${DEST}.new" "$DEST"
        rm -rf "${DEST}.old" 2>/dev/null || true

        echo "page_url=${PAGE_URL}" >> "$GITHUB_OUTPUT"
        echo "alive=true" >> "$GITHUB_OUTPUT"
        echo "deploy-pages: deployed to ${PAGE_URL}"
```

- [ ] **Step 2: Commit**

```bash
git add compose/files/actions/deploy-pages/
git commit -m "feat(pages): add deploy-pages composite action"
```

### Task 9: Create reference workflow template

**Files:**
- Create: `compose/files/actions/pages-template.yml`

- [ ] **Step 1: Write the template**

```yaml
name: Cove Pages

on:
  push:
    branches: [pages]

permissions:
  contents: read

jobs:
  build-and-deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Configure Pages
        id: pages
        uses: http://forgejo:3000/cove/configure-pages@main

      - name: Build with Hugo
        run: hugo --minify --baseURL "${{ steps.pages.outputs.base_url }}"

      - name: Upload artifact
        id: upload
        uses: http://forgejo:3000/cove/upload-pages-artifact@main
        with:
          path: public/

      - name: Deploy
        uses: http://forgejo:3000/cove/deploy-pages@main
        with:
          artifact_id: ${{ steps.upload.outputs.artifact_id }}
          owner: ${{ github.repository_owner }}
          repo: ${{ github.event.repository.name }}
```

- [ ] **Step 2: Commit**

```bash
git add compose/files/actions/pages-template.yml
git commit -m "feat(pages): add pages workflow template"
```

---

## Chunk 3: Provisioning

### Task 10: Create provision_pages.yml

**Files:**
- Create: `compose/provision_pages.yml`

Idempotent playbook. Generates an admin API token, checks for the `cove` org, creates four repos, and pushes action code via the Forgejo API.

- [ ] **Step 1: Write the playbook**

```yaml
- name: Provision Cove Pages (actions + artifact store)
  hosts: localhost
  gather_facts: true
  vars:
    actions_dir: "{{ playbook_dir }}/files/actions"

  tasks:
    - name: Check Forgejo is reachable
      ansible.builtin.uri:
        url: "{{ forgejo_root_url }}api/v1/version"
        status_code: [200, 403]
        validate_certs: false
      register: forgejo_check

    - name: Fail if Forgejo unreachable
      ansible.builtin.fail:
        msg: "Forgejo not responding at {{ forgejo_root_url }}. Run bringup.yml and provision_forgejo.yml first."
      when: forgejo_check.status not in [200, 403]

    - name: Delete stale cove-provision token
      ansible.builtin.command:
        argv:
          - docker
          - exec
          - --user
          - git
          - "{{ forgejo_container_name }}"
          - forgejo
          - --config
          - /data/gitea/conf/app.ini
          - admin
          - user
          - delete-access-token
          - --username
          - "{{ admin_username }}"
          - --token-name
          - "cove-provision"
      changed_when: true
      failed_when: false

    - name: Generate provisioning API token
      ansible.builtin.command:
        argv:
          - docker
          - exec
          - --user
          - git
          - "{{ forgejo_container_name }}"
          - forgejo
          - --config
          - /data/gitea/conf/app.ini
          - admin
          - user
          - generate-access-token
          - --username
          - "{{ admin_username }}"
          - --token-name
          - "cove-provision"
          - --scopes
          - "write:user,write:repository,write:admin"
      register: token_out
      changed_when: true
      no_log: true

    - name: Extract API token
      ansible.builtin.set_fact:
        api_token: >-
          {{ token_out.stdout
             | regex_search('Access token was successfully created:\s*(\S+)', '\1')
             | default([token_out.stdout | regex_search('([a-f0-9]{40})', '\1')])
             | select('string')
             | first }}
      no_log: true

    - name: Check for cove organization
      ansible.builtin.uri:
        url: "{{ forgejo_root_url }}api/v1/orgs/cove"
        headers:
          Authorization: "token {{ api_token }}"
        status_code: [200, 404]
        validate_certs: false
      register: cove_org_check

    - name: Create cove organization
      ansible.builtin.uri:
        url: "{{ forgejo_root_url }}api/v1/orgs"
        method: POST
        headers:
          Authorization: "token {{ api_token }}"
          Content-Type: application/json
        body_format: json
        body:
          username: cove
          full_name: "Cove Platform"
          description: "Cove platform actions and artifacts"
          visibility: "limited"
        status_code: [201, 422]
        validate_certs: false
      when: cove_org_check.status == 404

    - name: Create Cove Pages repositories
      ansible.builtin.uri:
        url: "{{ forgejo_root_url }}api/v1/orgs/cove/repos"
        method: POST
        headers:
          Authorization: "token {{ api_token }}"
          Content-Type: application/json
        body_format: json
        body:
          name: "{{ item }}"
          description: "Cove {{ item }}"
          auto_init: true
          default_branch: main
        status_code: [201, 409]
        validate_certs: false
      loop:
        - configure-pages
        - upload-pages-artifact
        - deploy-pages
        - pages-artifacts

    - name: Push action code via Forgejo API
      ansible.builtin.uri:
        url: "{{ forgejo_root_url }}api/v1/repos/cove/{{ item.repo }}/contents/{{ item.file }}"
        method: PUT
        headers:
          Authorization: "token {{ api_token }}"
          Content-Type: application/json
        body_format: json
        body:
          content: "{{ lookup('file', actions_dir + '/' + item.repo + '/' + item.file) | b64encode }}"
          message: "feat: provision {{ item.repo }} action"
          branch: main
        status_code: [200, 201]
        validate_certs: false
      loop:
        - { repo: "configure-pages", file: "action.yml" }
        - { repo: "upload-pages-artifact", file: "action.yml" }
        - { repo: "deploy-pages", file: "action.yml" }

    - name: Print provisioning summary
      ansible.builtin.debug:
        msg: |
          Cove Pages provisioned.
            Org: cove
            Repos:
              - cove/configure-pages (composite action)
              - cove/upload-pages-artifact (composite action)
              - cove/deploy-pages (composite action)
              - cove/pages-artifacts (artifact store)

          Action URLs for workflows:
            http://forgejo:3000/cove/configure-pages@main
            http://forgejo:3000/cove/upload-pages-artifact@main
            http://forgejo:3000/cove/deploy-pages@main

          Next: copy {{ actions_dir }}/pages-template.yml to any project's
          .forgejo/workflows/pages.yml and push to the pages branch.
```

- [ ] **Step 2: Commit**

```bash
git add compose/provision_pages.yml
git commit -m "feat(pages): add provision_pages.yml Ansible playbook"
```

---

## Verification

- [ ] **Step 11: Verify directory structure**

```bash
ls compose/{nginx,dnsmasq,files/actions/{configure-pages,upload-pages-artifact,deploy-pages}}
```

Expected: all directories and files present.

- [ ] **Step 12: Verify docker-compose.yml syntax**

```bash
docker compose -f compose/docker-compose.yml config --quiet
```

Expected: exit 0.

- [ ] **Step 13: Final commit**

```bash
git status
git add -A
git commit -m "feat(pages): complete Cove Pages infrastructure and actions"
```
