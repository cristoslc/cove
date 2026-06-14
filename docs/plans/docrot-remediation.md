# Plan: Docrot Remediation

**Date:** 2026-06-13

**Problem:** The project's .md files have significant docrot — they describe k3s/Lima/Kaniko architecture that was replaced months ago with Docker Compose/Colima/mkcert. Swain governance artifacts (AGENTS.md governance block, swain skill directories, swain settings) are present but unused. Dead k3s-era code (roles/, playbooks/, scripts/) clutters the repo.

**Goal:** Strip swain, remove dead code, fix all stale .md files to match current architecture.

## Changes

### 1. AGENTS.md — Strip swain governance block

Replace the full swain governance block (lines 5-85) with a brief cove-specific guidance section. Keep only the existing Cove-specific notes.

**Files:** `AGENTS.md`

### 2. Remove swain artifacts

- Delete .agents/skills/swain/ (18 swain skill directories)
- Delete skills-lock.json
- Delete swain.settings.json
- Delete .swain/ init marker directory
- Delete .crush/ swain symlinks
- Delete .agents/update-backup/ (backup files)
- Update .gitignore: remove swain-specific ignore patterns, keep cove-generated docs patterns

**Files:** `.agents/skills/swain*`, `skills-lock.json`, `swain.settings.json`, `.swain/`, `.crush/`, `.agents/update-backup/`, `.gitignore`

### 3. Remove dead k3s-era code

- Delete roles/cove/ (9 task files, 4 templates, 3 checksums — never called, never referenced by any active playbook)
- Delete playbooks/ (deploy.yml, teardown.yml — never called)
- Delete scripts/ (5 unused shell scripts: teardown-old, migrate-forgejo, cache-ssh-keys, add-cove-hosts, cert-renew)
- Delete compose/com.cove.forgejo-cert-renew.plist (Tailscale cert renewal launchd plist — replaced by mkcert)
- Delete .worktrees/infra/ (stale worktree artifact from k3s era)
- Delete .ansible/ (orphaned collection cache)
- Delete .crush/ directory (swain symlinks)
- Update cli/cove/project.py: remove reference to playbooks/

**Files:** `roles/`, `playbooks/`, `scripts/`, `compose/com.cove.forgejo-cert-renew.plist`, `.worktrees/infra/`, `.ansible/`, `.crush/`, `cli/cove/project.py`

### 4. Fix core docs

**PURPOSE.md:**
- Docker Desktop → a container runtime (Colima on macOS, Docker Engine on Linux)
- Remove "CI runner is a single agent" (no runner container deployed yet)

**README.md:**
- Install command: `cove` → `cove-cli`
- Services table: remove Tailscale FQDN:3000, add nginx/dnsmasq, use `git.cove`/`vault.cove` URLs
- Architecture diagram: show actual provisioning flow (batch-pull → bringup → bootstrap → provision)
- Remove VISION-001 artifact reference
- Add links to architecture docs

**docs/architecture.md (major rewrite):**
- System boundaries diagram: Colima, mkcert, nginx (:8080/:8443), pf NAT, no Tailscale FQDN hardcoded
- Vault: no host port mapping, accessed through nginx at `vault.cove`
- nginx ports: `127.0.0.1:8443` (HTTPS), `:8080` (HTTP), pf NAT `:443` → `:8443`
- TLS: mkcert primary, Tailscale cert secondary
- Registry context: entry point `https://git.cove/v2/` (not `forgejo.cove.local`)
- Forge bounded context: entry point `https://git.cove/` (not Tailscale FQDN)
- Pages bounded context: entry point `https://<owner>.pages.cove/` (not Tailscale FQDN)
- Data dir: mkcert certs `cove.local.pem` / `cove.local-key.pem`
- Provisioning pipeline: remove k3s/kata mentions, add Colima + mkcert + pf NAT steps
- Network boundaries: fix nginx ports, Vault row (no host port, via nginx)
- TLS section: mkcert wildcard certs primary
- Remove Future: k3s Architecture section entirely
- Update bringup summary URLs

**docs/abstractions.md:**
- Registry entry point: `forgejo.cove.local` → `git.cove`
- Secret lifecycle: add disk cache stage before Vault

**docs/pages.md:**
- Remove TLS limitation section (mkcert wildcards work, no browser warnings)
- Update URLs: `{owner}.pages.cove.{fqdn}` → `{owner}.pages.cove`
- Remove certificate warning troubleshooting entry

### 5. Remove stale swain artifacts

- Delete docs/vision/ (VISION-001 — describes k3s/Lima/Kaniko, not actual architecture)
- Delete docs/epic/ (EPIC-001 — describes k3s/kata/age-encryption, not actual)
- Delete docs/spec/ (SPEC-001 — describes cove build/tryup that don't exist)
- Delete docs/superpowers/ (k3s-era design docs)
- Delete docs/plans/cove-registry-consolidation.md (fully implemented)
- Delete docs/plans/nginx-sole-ingress.md (fully implemented)

**Files:** `docs/vision/`, `docs/epic/`, `docs/spec/`, `docs/superpowers/`, `docs/plans/cove-registry-consolidation.md`, `docs/plans/nginx-sole-ingress.md`

### 6. Minor fixes

- compose/.env.example: match current variables (no FORGEJO_HTTP_BIND, VAULT_BIND, etc.)
- docs/adr/list-adr.md: add ADR-014 entry

**Files:** `compose/.env.example`, `docs/adr/list-adr.md`

## Verification

1. `git status` shows only intended changes (no unexpected modifications)
2. No remaining references to swain in project files
3. No remaining references to roles/ or playbooks/ in active code
4. Docs describe current architecture: Compose + Colima + mkcert + git.cove/vault.cove

## Deferred

- Completely removing the swain skills from the available_skills list in the agent system prompt is not controlled by this repo
- Updating docs/superpowers/specs/2026-05-02-cove-design.md was superseded by deleting the whole superpowers directory