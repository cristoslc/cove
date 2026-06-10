# Cove Local DNS — Drop Tailscale Dependency

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace all Tailscale-dependent DNS and TLS with local dnsmasq + mkcert, so Cove runs fully offline without Tailscale.

**Architecture:** dnsmasq resolves `*.cove.local → 127.0.0.1` on port 5353. macOS `/etc/resolver/cove.local` directs `.cove.local` queries to dnsmasq. mkcert generates a locally-trusted wildcard cert for `*.cove.local`. nginx serves HTTPS on 8443 (with Tailscale Serve proxying 443→8443 as an optional overlay). Forgejo ROOT_URL becomes `https://git.cove.local/`.

**Tech Stack:** dnsmasq, mkcert, nginx, Ansible, macOS resolver

---

### Task 1: Update dnsmasq config for `cove.local`

**Files:**
- Modify: `compose/dnsmasq/cove.conf.j2`
- Modify: `compose/dnsmasq/cove.conf`
- Modify: `compose/group_vars/all.yml`

- [ ] **Step 1: Update `cove_domain` default in group_vars**

Change `ts_dns_name` references to use `cove_domain` variable defaulting to `cove.local`:

```yaml
# group_vars/all.yml
cove_domain: "cove.local"
```

Remove `ts_dns_name` default. It will be set dynamically only when Tailscale is detected (for the optional overlay).

- [ ] **Step 2: Update dnsmasq template**

In `compose/dnsmasq/cove.conf.j2`, change:
```
address=/cove.{{ ts_dns_name }}/127.0.0.1
```
to:
```
address=/cove.{{ cove_domain }}/127.0.0.1
```

- [ ] **Step 3: Update the static fallback `cove.conf`**

In `compose/dnsmasq/cove.conf`, change:
```
address=/cove.mbpbk-202602.taila90e7.ts.net/127.0.0.1
```
to:
```
address=/cove.local/127.0.0.1
```

- [ ] **Step 4: Commit**

```bash
git add compose/dnsmasq/ compose/group_vars/all.yml
git commit -m "feat: change default domain from tailscale FQDN to cove.local"
```

---

### Task 2: Update nginx template for `cove.local`

**Files:**
- Modify: `compose/nginx/default.conf.j2`
- Modify: `compose/nginx/default.conf` (static fallback)

- [ ] **Step 1: Update nginx template**

In `compose/nginx/default.conf.j2`, replace all `{{ ts_dns_name }}` references with `{{ cove_domain }}`. The server blocks become:
- `server_name git.cove.{{ cove_domain }};`
- `server_name ~^[a-zA-Z0-9-]+\.pages\.cove\.{{ cove_domain | regex_escape }}$;`
- Redirect block: `server_name git.cove.{{ cove_domain }} ~^.+\.pages\.cove\.{{ cove_domain | regex_escape }}$;`

- [ ] **Step 2: Update static fallback**

In `compose/nginx/default.conf`, replace the Tailscale FQDN with `cove.local`.

- [ ] **Step 3: Commit**

```bash
git add compose/nginx/
git commit -m "feat: nginx template uses cove.local domain"
```

---

### Task 3: Generate mkcert wildcard cert and configure nginx

**Files:**
- Modify: `compose/group_vars/all.yml`
- Modify: `compose/bringup.yml`
- Create: `scripts/gen-local-certs.sh`

- [ ] **Step 1: Add cert variables to group_vars**

Add:
```yaml
# --- TLS (local) ---
cove_domain: "cove.local"
cert_dir: "{{ cove_data_root }}/certs"
```

- [ ] **Step 2: Add mkcert cert generation to bringup.yml**

Add tasks after "Create cove data directories":
1. Check if `mkcert` is installed
2. If not, install via Homebrew (`brew install mkcert`)
3. Run `mkcert -install` (installs local CA)
4. Generate wildcard cert: `mkcert -key-file {{ cert_dir }}/privkey.pem -cert-file {{ cert_dir }}/fullchain.pem "*.{{ cove_domain }}" "git.{{ cove_domain }}"`
5. This replaces the Tailscale cert-renew approach

- [ ] **Step 3: Create `scripts/gen-local-certs.sh`**

A standalone script that generates the certs (for manual use or CI).

- [ ] **Step 4: Commit**

```bash
git add compose/group_vars/all.yml compose/bringup.yml scripts/
git commit -m "feat: add mkcert local cert generation, remove tailscale cert dependency"
```

---

### Task 4: Add macOS resolver for `cove.local`

**Files:**
- Modify: `compose/bringup.yml`
- Create: `scripts/add-cove-resolver.sh`

- [ ] **Step 1: Add resolver task to bringup.yml**

Add a task (with `become: true`, `ignore_errors: true`) that creates `/etc/resolver/cove.local`:
```
nameserver 127.0.0.1
port 5353
```

- [ ] **Step 2: Update `scripts/add-cove-hosts.sh`**

Rename to `scripts/add-cove-resolver.sh` and update it to:
1. Create `/etc/resolver/cove.local` with nameserver 127.0.0.1 port 5353
2. Remove old `/etc/hosts` cove entries (they're no longer needed)

- [ ] **Step 3: Commit**

```bash
git add compose/bringup.yml scripts/
git commit -m "feat: add macOS resolver for cove.local via dnsmasq"
```

---

### Task 5: Update bringup.yml to remove Tailscale dependency

**Files:**
- Modify: `compose/bringup.yml`
- Modify: `compose/group_vars/all.yml`

- [ ] **Step 1: Restructure bringup.yml**

The Tailscale serve step becomes **optional** — it adds HTTPS on port 443 via Tailscale as an overlay, but the core stack works without it:

1. Remove `Point tailscale FQDN to localhost in hosts file` (no longer needed)
2. Change `Set Forgejo URLs through nginx proxy` to use `cove_domain` unconditionally:
   ```yaml
   forgejo_domain: "git.cove.{{ cove_domain }}"
   forgejo_root_url: "https://git.cove.{{ cove_domain }}/"
   ```
3. Keep the Tailscale detect + serve block as an **optional overlay** that only runs if Tailscale is detected
4. The mkcert cert generation is the primary TLS path

- [ ] **Step 2: Update `scripts/cert-renew.sh`**

Replace the Tailscale cert renewal with mkcert regeneration:
```bash
#!/bin/bash
set -euo pipefail
COVE_DATA_ROOT="${COVE_DATA_ROOT:-$HOME/Documents/cove-data}"
CERT_DIR="$COVE_DATA_ROOT/certs"
mkcert -key-file "$CERT_DIR/privkey.pem" -cert-file "$CERT_DIR/fullchain.pem" "*.cove.local" "git.cove.local"
docker restart cove-nginx
```

- [ ] **Step 3: Commit**

```bash
git add compose/bringup.yml compose/group_vars/all.yml scripts/
git commit -m "feat: make tailscale optional, cove.local is the default domain"
```

---

### Task 6: Update action configs and compose env

**Files:**
- Modify: `compose/group_vars/all.yml`
- Modify: `compose/files/actions/configure-pages/action.yml`
- Modify: `compose/files/actions/deploy-pages/action.yml`
- Modify: `compose/files/actions/upload-pages-artifact/action.yml`
- Modify: `compose/docker-compose.yml`

- [ ] **Step 1: Update COVE_FQDN defaults in actions**

In all three action YAMLs, change the fallback from `mbpbk-202602.taila90e7.ts.net` to `cove.local`.

- [ ] **Step 2: Update docker-compose.yml ports**

The nginx ports stay at 8080/8443 for Docker Desktop compatibility. But the Forgejo ROOT_URL env var should now use `cove_domain`.

- [ ] **Step 3: Commit**

```bash
git add compose/
git commit -m "feat: update action fallbacks and compose env for cove.local"
```

---

### Task 7: Update git remotes and cove guidance

**Files:**
- Modify: `~/.agents/agents-md-detail/cove.md`

- [ ] **Step 1: Update Cove guidance**

Update `~/.agents/agents-md-detail/cove.md` to reflect:
- Domain is `cove.local` (no Tailscale dependency)
- DNS via dnsmasq + macOS resolver
- TLS via mkcert (locally trusted CA)
- Tailscale Serve is an optional overlay for remote access

- [ ] **Step 2: Update git remotes**

```bash
git remote set-url fjl http://git.cove.local:3000/cristos/cove
git remote set-url fjl --push http://git.cove.local:3000/cristos/cove
```

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "docs: update cove guidance for cove.local domain"
```

---

### Task 8: Smoke test and verify

- [ ] **Step 1: Run bringup playbook**

```bash
ansible-playbook -i compose/inventory.yml compose/bringup.yml
```

- [ ] **Step 2: Verify DNS resolution**

```bash
dig @127.0.0.1 -p 5353 git.cove.local
dig @127.0.0.1 -p 5353 test.pages.cove.local
```

- [ ] **Step 3: Verify HTTPS**

```bash
curl -sk https://git.cove.local:8443/api/healthz
curl -sk https://test.pages.cove.local:8443/_health
```

- [ ] **Step 4: Verify mkcert cert is trusted**

```bash
openssl s_client -connect git.cove.local:8443 </dev/null 2>/dev/null | head -5
```

- [ ] **Step 5: Push branch and create PR**