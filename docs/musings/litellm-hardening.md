# LiteLLM Hardening Guide

## Context

LiteLLM has accumulated 16+ CVEs and a supply chain compromise in 2025-2026. The worst chain scores CVSS 10.0 (unauthenticated RCE). This musing captures hardening strategies for running LiteLLM safely, especially in Cove's local-first deployment.

## Threat Model

For Cove: single-user, localhost-only, trusted operator. This eliminates most network-based CVEs but does not eliminate supply chain risk.

## Hardening Layers

### 1. Network Isolation (Eliminates ~60% of CVEs)

Most LiteLLM CVEs require network access to exploit:
- CVE-2026-42271 (command injection) — needs API key + network
- CVE-2026-42208 (SQL injection) — unauthenticated but needs network
- CVE-2026-49468 (Host header injection) — needs direct internet exposure
- CVE-2026-47101/47102/40217 (auth bypass chain) — needs API access

**Rules:**
- Bind to `127.0.0.1` only, never `0.0.0.0`
- Never expose directly to the internet without a reverse proxy (Caddy, nginx) that validates Host headers
- If external access is needed, put a WAF or reverse proxy in front that terminates TLS and validates Host
- Use a dedicated network namespace / Docker network with no external routes

### 2. Version Pinning (Eliminates Known CVEs)

- Pin to `litellm>=1.84.0` (fixes CVE-2026-49468 and cumulative prior fixes)
- Pin by hash: `pip install litellm==1.84.0 --hash=sha256:...`
- Do not use `latest` tags in Docker
- Subscribe to GitHub Security Advisories for BerriAI/litellm
- Set up Dependabot or Renovate with auto-merge disabled — review advisories before bumping

### 3. Supply Chain Defense

The March 2026 TeamPCP attack compromised PyPI credentials via a Trivy GitHub Action. Mitigations:

- **Vendor the dependency** — check the wheel into Cove's repo or a private registry (Forgejo). Eliminates PyPI as a live attack surface.
- **Hash pinning** — even if not vendoring, pin by hash so any tampered release fails to install.
- **Staged adoption** — never auto-pull the latest release. Wait 48-72 hours after a release before adopting. Let the community find supply chain malware first.
- **Minimal base image** — use `python:3.13-slim`, not `python:3.13`. Fewer packages = smaller attack surface.
- **Read-only filesystem** — run container with `--read-only`. If LiteLLM needs to write (logs, DB), mount a tmpfs or volume at the specific path.

### 4. Disable Unused Features

LiteLLM ships with many endpoints enabled by default. Most are unnecessary for a proxy-only deployment:

- **Disable the Admin UI** — `--port 4000` is the proxy, the UI on another port is unnecessary. Don't expose it.
- **Disable user management** — if you're the only user, you don't need `/user/new`, `/user/update`, etc. Block these routes.
- **Disable MCP endpoints** — CVE-2026-42271 is a command injection in MCP test endpoints. If you don't use MCP, disable it.
- **Disable `/prompts/test`** — CVE-2026-42203 (SSTI) lives here.
- **Disable JWT auth** — CVE-2026-35030 only affects deployments with `enable_jwt_auth` on. Leave it off unless you need it.

**Implementation:** Use LiteLLM's `allowed_routes` configuration to whitelist only the routes you need:
```
allowed_routes:
  - /chat/completions
  - /models
  - /health
```

### 5. Credential Hygiene

LiteLLM is a credential concentrator — it holds API keys for every provider it proxies. If compromised, an attacker gets all of them.

- **Use short-lived keys** — rotate provider API keys regularly. If LiteLLM is compromised, the blast radius is bounded by key lifetime.
- **Separate keys per environment** — don't use the same Anthropic/OpenAI key for dev and prod.
- **Environment variables, not config files** — pass API keys via `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` env vars, not in a config file that could be read from the filesystem.
- **Docker secrets** — if using Docker Swarm, use `--secret` instead of env vars.

### 6. Monitoring and Detection

- **Log all requests** — LiteLLM's logging captures request paths, status codes, and latency. Ship logs to a local Loki or just to stdout.
- **Alert on unexpected routes** — if `/key/generate` is called and you never use it, that's a compromise signal.
- **Monitor for known-exploited CVEs** — CISA added CVE-2026-42271 to its KEV catalog. Check periodically.
- **Health check endpoint** — use `/health` to verify the proxy is up. If it goes down, your agents fail open (no compression) or fail closed (no LLM access) depending on config.

### 7. The "Fail Open" Decision

LiteLLM's Headroom integration has a reliability guarantee: "If Headroom goes down, your LLM calls are unaffected." This is the right default — compression is an optimization, not a gating function.

But consider: if LiteLLM itself goes down, do you want agents to fail open (direct to provider) or fail closed (no LLM access)?

- **Fail open** — agents bypass the proxy and call providers directly. Better for productivity, worse for auditability.
- **Fail closed** — agents stop working. Better for security (no unmonitored traffic), worse for productivity.

For Cove: fail open is fine. The threat model doesn't justify blocking all LLM access when the proxy is down.

## Summary Checklist

- [ ] Bind to 127.0.0.1 only
- [ ] Pin to litellm>=1.84.0 with hash
- [ ] Vendor the wheel or use private registry
- [ ] Read-only container filesystem
- [ ] Disable unused routes (MCP, admin UI, user management, /prompts/test)
- [ ] Use environment variables for API keys
- [ ] Rotate provider keys regularly
- [ ] Log all requests, monitor for unexpected routes
- [ ] Fail open when proxy is down
- [ ] Subscribe to BerriAI/litellm security advisories
