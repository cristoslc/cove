# OpenCode Tier-1 MVP — Cove Compose Integration

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add OpenCode as a Cove tier-1 service behind Caddy (auth-bypass pattern) and nginx (TLS termination), accessible at `opencode.cove`.

**Architecture:** Two new compose services — `opencode` (internal, port 4095) and `caddy` (internal, port 4096, bcrypt basic auth + `header_up Authorization` bypass). nginx gets a new `opencode.cove` server block proxying to `caddy:4096`. Credentials flow: 1Password → Vault → `.env` → compose. Caddy config is rendered from a Jinja2 template at bringup time.

**Tech Stack:** Docker Compose, Ansible (bringup.yml), nginx (default.conf.j2), Caddy (custom Dockerfile), Jinja2 templating, 1Password + Vault for secrets.

**Auth architecture:** nginx+Caddy stack (matches operator's working reference pattern). nginx-only with ported `proxy_set_header Authorization` is deferred to v1.

---

## Chunk 1: Compose Services + Caddy Image

### Task 1.1: Add opencode and caddy services to docker-compose.yml

**Files:**
- Modify: `compose/docker-compose.yml`

- [ ] **Step 1: Add opencode service block**

After the `vault` service block, add:

```yaml
  opencode:
    image: ${OPENCODE_IMAGE:-ghcr.io/anomalyco/opencode:latest}
    container_name: ${OPENCODE_CONTAINER_NAME:-cove-opencode}
    restart: unless-stopped
    environment:
      OPENCODE_SERVER_USERNAME: ${OPENCODE_SERVER_USERNAME:-opencode}
      OPENCODE_SERVER_PASSWORD: ${OPENCODE_SERVER_PASSWORD}
      OPENCODE_SERVER_HOSTNAME: 0.0.0.0
      OPENCODE_SERVER_PORT: "4095"
    volumes:
      - ${OPENCODE_CODE_DIR:-~}:/home/code:rw
      - ${OPENCODE_PROJECTS_DIR:-~}:/home/projects:rw
      - ${OPENCODE_DATA_DIR:-~}:/home/opencode/.local/share/opencode:rw
      - ${OPENCODE_CONFIG_DIR:-~}:/home/opencode/.config/opencode:rw
    deploy:
      resources:
        limits:
          memory: 2G
          cpus: "1.0"
```

- [ ] **Step 2: Add caddy service block**

After the opencode block, add:

```yaml
  caddy:
    build: ${CADDY_CONF_DIR:-./caddy}
    container_name: ${CADDY_CONTAINER_NAME:-cove-caddy}
    restart: unless-stopped
    depends_on:
      opencode:
        condition: service_started
    volumes:
      - ${COVE_DATA_ROOT}/caddy/Caddyfile:/etc/caddy/Caddyfile:ro
    ports:
      - "127.0.0.1:4096:4096"
```

Note: Caddy publishes port 4096 to localhost only — nginx proxies to it internally via the Docker network (`caddy:4096`), but the host port is needed for the LAN phone-access case (MVP: phone on same WiFi opens `http://laptop.local:4096`).

- [ ] **Step 3: Commit**

```bash
git add compose/docker-compose.yml
git commit -m "feat: add opencode and caddy services to compose stack"
```

### Task 1.2: Create Caddy Dockerfile and default Caddyfile template

**Files:**
- Create: `compose/caddy/Dockerfile`
- Create: `compose/caddy/Caddyfile.j2`

- [ ] **Step 1: Create Caddy Dockerfile**

```dockerfile
FROM caddy:2-alpine
COPY Caddyfile /etc/caddy/Caddyfile
```

- [ ] **Step 2: Create Caddyfile.j2 template**

```caddyfile
:4096 {
	log {
		output stdout
		format console
		level INFO
	}

	basic_auth {
		{{ opencode_caddy_user }} {{ opencode_caddy_hash }}
	}

	reverse_proxy opencode:4095 {
		header_up Authorization "Basic {{ opencode_auth_b64 }}"
		header_down Content-Security-Policy "default-src 'self' ; script-src 'self' 'unsafe-inline' 'unsafe-eval' 'wasm-unsafe-eval' ; style-src 'self' 'unsafe-inline' ; connect-src 'self' data: https://opencode.ai ; img-src 'self' data: blob: ; font-src 'self' data:"
	}
}
```

Variables `opencode_caddy_user`, `opencode_caddy_hash`, and `opencode_auth_b64` are rendered by Ansible at bringup time from Vault/1Password credentials.

- [ ] **Step 3: Commit**

```bash
git add compose/caddy/
git commit -m "feat: add Caddy Dockerfile and Caddyfile.j2 template"
```

---

## Chunk 2: Ansible Integration (bringup.yml)

### Task 2.1: Add opencode variables to group_vars/all.yml

**Files:**
- Modify: `compose/group_vars/all.yml`

- [ ] **Step 1: Add opencode and caddy variable blocks**

After the dnsmasq block, add:

```yaml
# --- OpenCode ---
opencode_image: "ghcr.io/anomalyco/opencode:latest"
opencode_container_name: cove-opencode
opencode_code_dir: "{{ ansible_env.HOME }}/Documents/code"
opencode_projects_dir: "{{ ansible_env.HOME }}/Documents/projects"
opencode_data_dir: "{{ ansible_env.HOME }}/Documents/cove/opencode"
opencode_config_dir: "{{ ansible_env.HOME }}/.config/opencode"
opencode_server_username: opencode
opencode_server_port: 4095
opencode_caddy_port: 4096
opencode_1p_ref: "op://{{ op_vault }}/OpenCode Server"

# --- Caddy ---
caddy_conf_dir: "{{ playbook_dir }}/caddy"
caddy_container_name: cove-caddy
```

- [ ] **Step 2: Commit**

```bash
git add compose/group_vars/all.yml
git commit -m "feat: add opencode and caddy variables to group_vars"
```

### Task 2.2: Add opencode data directory and Caddy config rendering to bringup.yml

**Files:**
- Modify: `compose/bringup.yml`

- [ ] **Step 1: Add opencode data directory**

In the "DATA DIRECTORIES" task, add to the loop:

```yaml
        - "{{ cove_data_root }}/caddy"
```

- [ ] **Step 2: Add Caddy config rendering task**

After the "Render dnsmasq config from template" task, add:

```yaml
    - name: Check htpasswd and op prerequisites
      ansible.builtin.command: which htpasswd
      register: htpasswd_check
      changed_when: false
      failed_when: false

    - name: Check op CLI available
      ansible.builtin.command: which op
      register: op_check
      changed_when: false
      failed_when: false

    - name: Fetch OpenCode credentials from 1Password
      when: op_check.rc == 0
      ansible.builtin.command:
        argv:
          - op
          - read
          - "{{ opencode_1p_ref }}/username"
      register: oc_username_raw
      changed_when: false
      no_log: true

    - name: Fetch OpenCode password from 1Password
      when: op_check.rc == 0
      ansible.builtin.command:
        argv:
          - op
          - read
          - "{{ opencode_1p_ref }}/password"
      register: oc_password_raw
      changed_when: false
      no_log: true

    - name: Generate bcrypt hash for Caddy basic auth
      when: htpasswd_check.rc == 0
      ansible.builtin.shell: |
        set -eo pipefail
        printf '%s' "{{ oc_password_raw.stdout }}" | htpasswd -niBC 12 "{{ oc_username_raw.stdout }}" | cut -d: -f2
      register: oc_bcrypt_hash
      changed_when: false
      no_log: true

    - name: Generate base64 auth header for auth-bypass
      when: htpasswd_check.rc == 0
      ansible.builtin.shell: |
        set -eo pipefail
        printf '%s' "{{ oc_username_raw.stdout }}:{{ oc_password_raw.stdout }}" | base64 | tr -d '\n'
      register: oc_auth_b64
      changed_when: false
      no_log: true

    - name: Render Caddy config from template
      ansible.builtin.template:
        src: "{{ caddy_conf_dir }}/Caddyfile.j2"
        dest: "{{ cove_data_root }}/caddy/Caddyfile"
        mode: "0644"
      vars:
        opencode_caddy_user: "{{ oc_username_raw.stdout }}"
        opencode_caddy_hash: "{{ oc_bcrypt_hash.stdout }}"
        opencode_auth_b64: "{{ oc_auth_b64.stdout }}"
```

- [ ] **Step 3: Add opencode env vars to .env rendering**

In the "Render compose .env" task, add to the `content:` block:

```yaml
          OPENCODE_IMAGE={{ opencode_image }}
          OPENCODE_CONTAINER_NAME={{ opencode_container_name }}
          OPENCODE_CODE_DIR={{ opencode_code_dir }}
          OPENCODE_PROJECTS_DIR={{ opencode_projects_dir }}
          OPENCODE_DATA_DIR={{ opencode_data_dir }}
          OPENCODE_CONFIG_DIR={{ opencode_config_dir }}
          OPENCODE_SERVER_USERNAME={{ opencode_server_username }}
          OPENCODE_SERVER_PASSWORD={{ oc_password_raw.stdout }}
          CADDY_CONF_DIR={{ caddy_conf_dir }}
          CADDY_CONTAINER_NAME={{ caddy_container_name }}
```

- [ ] **Step 4: Add opencode.cove to mkcert SAN list**

In the "Generate mkcert cert for *.cove" task, add `opencode.cove` to the argv list (after `hc.cove`):

```yaml
           - opencode.cove
```

- [ ] **Step 5: Add opencode.cove to cert validation**

In the "Validate TLS cert covers required hostnames" task, add `opencode.cove` to the for loop:

```yaml
        for host in "git.cove" "vault.cove" "hc.cove" "opencode.cove"; do
```

- [ ] **Step 6: Add opencode.cove to /etc/hosts**

In the "Add *.cove hostnames to /etc/hosts" task, add `opencode.cove` to the line:

```yaml
         line: "127.0.0.1 cove git.cove vault.cove hc.cove opencode.cove"
```

- [ ] **Step 7: Add opencode health check**

After the "Wait for Vault to respond" task, add:

```yaml
    - name: Wait for OpenCode to respond
      ansible.builtin.uri:
        url: "https://opencode.cove/"
        status_code: 200
        validate_certs: false
      register: opencode_health
      retries: 15
      delay: 2
      until: opencode_health.status == 200
```

- [ ] **Step 8: Add opencode to print summary**

In the "Print summary" task, add to the msg:

```yaml
            OpenCode: https://opencode.cove/ (TLS via nginx+mkcert, auth via Caddy)
```

- [ ] **Step 9: Commit**

```bash
git add compose/bringup.yml
git commit -m "feat: add opencode data dir, Caddy config rendering, cert, hosts, health check to bringup"
```

---

## Chunk 3: Nginx + .env.example

### Task 3.1: Add opencode.cove server block to nginx config

**Files:**
- Modify: `compose/nginx/default.conf.j2`

- [ ] **Step 1: Add opencode upstream and server block**

After the `vault_backend` upstream, add:

```nginx
upstream opencode_backend {
    server caddy:4096;
}
```

After the `vault.cove` server block (before the pages block), add:

```nginx
# opencode.cove — OpenCode AI coding harness (via Caddy auth-bypass)
server {
    listen 443 ssl;
    server_name opencode.cove;

    ssl_certificate     /certs/cove.local.pem;
    ssl_certificate_key /certs/cove.local-key.pem;

    location / {
        proxy_pass http://opencode_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

- [ ] **Step 2: Commit**

```bash
git add compose/nginx/default.conf.j2
git commit -m "feat: add opencode.cove nginx server block proxying to caddy"
```

### Task 3.2: Update .env.example

**Files:**
- Modify: `compose/.env.example`

- [ ] **Step 1: Add opencode and caddy env vars**

Append:

```
OPENCODE_IMAGE=ghcr.io/anomalyco/opencode:latest
OPENCODE_CONTAINER_NAME=cove-opencode
OPENCODE_CODE_DIR=~/Documents/code
OPENCODE_PROJECTS_DIR=~/Documents/projects
OPENCODE_DATA_DIR=~/Documents/cove/opencode
OPENCODE_CONFIG_DIR=~/.config/opencode
OPENCODE_SERVER_USERNAME=opencode
OPENCODE_SERVER_PASSWORD=<from 1Password>
CADDY_CONF_DIR=./caddy
CADDY_CONTAINER_NAME=cove-caddy
```

- [ ] **Step 2: Commit**

```bash
git add compose/.env.example
git commit -m "feat: add opencode and caddy env vars to .env.example"
```

---

## Chunk 4: Verification

### Task 4.1: Verify compose config is valid

- [ ] **Step 1: Validate docker-compose.yml syntax**

```bash
docker compose -f compose/docker-compose.yml config 2>&1 | head -5
```

Expected: no errors, services listed include opencode and caddy.

- [ ] **Step 2: Verify Caddy Dockerfile builds**

```bash
docker build -t cove-caddy-test compose/caddy/ 2>&1
```

Expected: `Successfully tagged cove-caddy-test:latest`.

### Task 4.2: Verify nginx config template renders

**Prerequisite:** `uv run --with jinja2 python3` (Jinja2 is not a project dependency, install on-demand).

- [ ] **Step 1: Test Jinja2 rendering of nginx config**

```bash
uv run --with jinja2 python3 -c "
from jinja2 import Template
with open('compose/nginx/default.conf.j2') as f:
    t = Template(f.read())
print(t.render())
" 2>&1 | grep -c 'opencode.cove'
```

Expected: `1` (one occurrence of opencode.cove in rendered output).

### Task 4.3: Verify Caddyfile template renders

**Prerequisite:** `uv run --with jinja2 python3` (Jinja2 is not a project dependency, install on-demand).

- [ ] **Step 1: Test Jinja2 rendering of Caddyfile**

```bash
uv run --with jinja2 python3 -c "
from jinja2 import Template
with open('compose/caddy/Caddyfile.j2') as f:
    t = Template(f.read())
print(t.render(opencode_caddy_user='test', opencode_caddy_hash='\$2a\$12\$hash', opencode_auth_b64='dGVzdDpwYXNz'))
" 2>&1 | grep -c 'header_up Authorization'
```

Expected: `1` (auth-bypass header present in rendered output).

### Task 4.4: Run existing test suite

- [ ] **Step 1: Run CLI tests**

```bash
uv run --directory cli pytest cli/tests/ -v
```

Expected: all existing tests pass (no regressions from compose changes).

---

## Out of Scope (deferred to follow-up work)

- Running `cove up` end-to-end (requires 1Password credentials, sudo for /etc/hosts, mkcert)
- Testing session persistence across container restarts
- Testing phone access from same LAN
- Porting auth-bypass to nginx-only (v1)
- Config hot-reload verification spike
- XDG path verification spike
- Container-lifecycle restart spike
