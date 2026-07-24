# Plan: LiteLLM Hardening for Cove

## Status

Draft

## Motivation

LiteLLM has accumulated 16+ CVEs and a supply chain compromise in 2025-2026. The worst chain scores CVSS 10.0 (unauthenticated RCE). We want to offer LiteLLM as a Cove harbor service (for Headroom context compression proxy), but only if it can be deployed securely. The musing at `docs/musings/litellm-hardening.md` documents the threat model and mitigations. This plan implements them.

## Scope

- A Docker Compose profile for LiteLLM + Headroom in Cove
- Hardening applied: network isolation, version pinning, route lockdown, read-only filesystem
- Documentation: how to use it, what's secured, what's not
- No changes to Cove's core — this is an optional compose profile

## Out of Scope

- Multi-tenant LiteLLM deployment (Cove is single-user)
- Upstream LiteLLM patches (we pin and vendor, we don't fork)
- Sleev or DCP integration (separate concern)

## Tasks

### 1. Compose integration: `compose/docker-compose.yml` + `compose/litellm/`

LiteLLM and Headroom are added to the main compose file with `profiles: ["litellm"]` so they don't start with `cove up`. The `compose/litellm/` directory holds the Dockerfile and config.

- **Network:** `127.0.0.1:4000` only, no external exposure. Accessible via `litellm.cove` through nginx ingress.
- **Version:** `litellm>=1.84.0` pinned by hash
- **Routes:** whitelist only `/chat/completions`, `/models`, `/health`
- **Filesystem:** `read_only: true` container, tmpfs for logs/DB
- **Headroom:** sidecar container, local compression model, pinned image tag
- **Credentials:** env vars only (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`)
- **Health check:** `/health` endpoint with restart policy
- **Profiles:** `litellm` profile so `cove up` doesn't start it automatically

### 2. Cove integration: `scripts/cove-litellm.sh`

A script that:
- Checks prerequisites (Docker, compose)
- Starts the LiteLLM profile
- Prints the proxy URL and instructions for pointing OpenCode at it
- Supports `up`, `down`, `status`, `logs` subcommands

### 3. Documentation: `docs/litellm-proxy.md`

A user-facing doc covering:

- **Quick start:** `cove litellm up` → point OpenCode at `http://127.0.0.1:4000`
- **What's hardened:** network isolation, route whitelist, read-only container, hash-pinned versions
- **What's NOT hardened:** supply chain (we pin but don't vendor — tradeoff documented), JWT auth (disabled by design)
- **Credentials:** how to set `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`
- **Troubleshooting:** proxy won't start, Headroom model download fails, OpenCode can't connect
- **Upgrade procedure:** how to bump the pinned version safely (staged adoption: wait 48-72h after release)
- **Architecture diagram:** mermaid flowchart showing OpenCode → LiteLLM proxy → Headroom sidecar → upstream LLM provider

### 4. Update `docs/musings/litellm-hardening.md`

Add a "Resolved by" section at the top linking to the plan and the compose profile, so the musing's recommendations are traceable to implementation.

### 5. Update `AGENTS.md` (project root)

Add a section under "Cove-specific notes" documenting the LiteLLM service:
- How to start/stop it
- Security posture (pinned, isolated, read-only)
- That it's optional

## Files Changed

```
CREATE compose/litellm/Dockerfile
CREATE compose/litellm/config.yaml
CREATE cli/cove/litellm.py                 (Click group: cove litellm up|down|status|logs)
EDIT cli/cove/cli.py                       (register litellm group)
EDIT cli/cove/status.py                    (add LiteLLM/Headroom as optional services)
EDIT compose/docker-compose.yml            (add litellm + headroom services with profiles)
EDIT compose/nginx/default.conf.j2         (add litellm.cove upstream + server block)
EDIT compose/bringup.yml                   (add litellm.cove to cert SANs, hosts, .env)
CREATE docs/litellm-proxy.md
EDIT docs/musings/litellm-hardening.md     (add "Resolved by" section)
EDIT AGENTS.md                             (add LiteLLM service notes)
```

## Verification

1. `docker compose --project-directory compose up --profile litellm -d` starts without errors
2. `curl -H "Host: example.com" -H "Host: litellm.cove" https://127.0.0.1:8443/chat/completions` returns 404 (route whitelist working)
3. `curl -H "Host: litellm.cove" https://127.0.0.1:8443/health` returns 200
4. `curl -H "Host: litellm.cove" https://127.0.0.1:8443/key/generate` returns 404 (admin routes disabled)
5. OpenCode configured with `OPENAI_BASE_URL=https://litellm.cove/v1` can complete a chat round-trip
6. Container is `read_only: true` (verify with `docker inspect`)
7. `docs/litellm-proxy.md` renders without broken links
