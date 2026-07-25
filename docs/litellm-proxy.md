# LiteLLM Proxy for Cove

LiteLLM is a hardened LLM proxy that sits between your AI agents and upstream LLM providers (Anthropic, OpenAI). It provides Headroom context compression as a sidecar, reducing token usage and cost.

## Quick Start

```shell
# Set your API keys
export ANTHROPIC_API_KEY="sk-ant-..."
export OPENAI_API_KEY="sk-proj-..."

# Start the proxy
cove litellm up

# Check it's running
cove litellm status

# Point your tools at https://litellm.cove/
```

The proxy is accessible at `https://litellm.cove/` through Cove's nginx ingress (port 8443 → 443 via pf). The container itself binds to `127.0.0.1:4000` only — no external network exposure.

## What's Hardened

| Layer | Mitigation |
|-------|-----------|
| **Network** | Binds to `127.0.0.1` only. No external exposure. |
| **Version** | Pinned to `litellm==1.84.0` with multi-stage build. |
| **Routes** | Whitelist-only at nginx layer: `/health`, `/v1/models`, `/v1/*`. All other paths return 403. LiteLLM's built-in `allowed_routes` is Enterprise-only, so route lockdown is enforced by the reverse proxy. |
| **Filesystem** | Container runs `read_only: true`. Writable tmpfs for logs and DB. |
| **Supply chain** | Multi-stage build isolates pip install; hash-pinned in requirements. |
| **Base image** | `python:3.13-slim` — minimal package surface. |
| **Credentials** | API keys via environment variables only. No config files with secrets. |
| **Health check** | Docker health check on `/health` with restart policy. |
| **Memory limits** | 512M for LiteLLM, 256M for Headroom. |

## What's NOT Hardened

| Gap | Rationale |
|-----|-----------|
| **Supply chain (full)** | We pin but don't vendor. A PyPI compromise could still inject malware. Mitigation: staged adoption (wait 48-72h after release). |
| **JWT auth** | Disabled by design. Cove is single-user, localhost-only. JWT auth adds attack surface (CVE-2026-35030) with no benefit. |
| **Multi-tenancy** | Not supported. Cove is single-user. |
| **TLS termination** | Handled by Cove's nginx ingress at `https://litellm.cove/`. The container itself listens on plain HTTP at `127.0.0.1:4000`. |

## Credentials Setup

Set your Ollama Cloud API key before running `cove litellm up`:

```shell
export OLLAMA_API_KEY="ollama"
```

You can also put it in a `.env` file in the project root:

```shell
OLLAMA_API_KEY=ollama
```

## Configuration

The LiteLLM config lives at `~/Documents/cove-data/litellm/config.yaml`. It's rendered from a template on first `cove up`, then it's yours to edit. Subsequent `cove up` runs won't overwrite it — your changes persist.

To add a model:

```yaml
model_list:
  - model_name: my-custom-model
    litellm_params:
      model: openai/deepseek-v4-flash:cloud
      api_base: https://ollama.com/v1
      api_key: os.environ/OLLAMA_API_KEY
```

After editing, restart the proxy:

```shell
cove litellm down && cove litellm up
```

To reset to defaults, delete the file and re-run `cove up`:

```shell
rm ~/Documents/cove-data/litellm/config.yaml
cove up --no-provision
```

## Commands

```shell
cove litellm up       # Start the proxy
cove litellm down     # Stop the proxy
cove litellm status   # Check health
cove litellm logs     # Tail logs
cove litellm logs -f  # Follow logs
cove litellm logs -n 100  # Show last 100 lines
```

## Architecture

```mermaid
flowchart LR
    Agent["AI Agent\n(OpenCode, etc.)"]
    Nginx["Cove nginx\nlitellm.cove:443\nroute whitelist"]
    Proxy["LiteLLM Proxy\n127.0.0.1:4000"]
    Headroom["Headroom Sidecar\n127.0.0.1:4001"]
    Anthropic["Anthropic API"]
    OpenAI["OpenAI API"]

    Agent -->|https://litellm.cove/v1/...| Nginx
    Nginx -->|"allow: /health, /v1/*\nblock: everything else"| Proxy
    Proxy -->|compress context| Headroom
    Proxy -->|proxy request| Anthropic
    Proxy -->|proxy request| OpenAI
    Headroom -->|compressed context| Proxy
```

## Troubleshooting

### Proxy won't start

```shell
cove litellm logs
```

Common causes:
- Port 4000 is already in use: `lsof -i :4000`
- Missing API keys: check `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` are set
- Docker not running: `docker info`

### Headroom model download fails

Headroom downloads a compression model on first start. If it fails:
- Check internet connectivity
- Check `cove-headroom` logs: `docker logs cove-headroom`
- The proxy will still work (Headroom has a "fail open" guarantee)

### OpenCode can't connect

```shell
curl -H "Host: litellm.cove" https://127.0.0.1:8443/health
curl -H "Host: litellm.cove" https://127.0.0.1:8443/v1/models
```

If both work, configure OpenCode to use the proxy by setting the environment variable:

```shell
export OPENAI_BASE_URL=https://litellm.cove/v1
```

Or in `opencode.json`:

```json
{
  "provider": "openai",
  "apiBase": "https://litellm.cove/v1"
}
```

### Admin routes accessible

If you can reach `/key/generate` or other admin routes, the nginx route whitelist is not working. Check that the `litellm.cove` server block in `compose/nginx/default.conf` has the whitelist locations and the catch-all `return 403`.

## Upgrade Procedure

1. **Wait 48-72 hours** after a LiteLLM release before upgrading. Let the community find supply chain malware first.
2. Check the [LiteLLM release notes](https://github.com/BerriAI/litellm/releases) and [security advisories](https://github.com/BerriAI/litellm/security/advisories).
3. Update the version pin in `compose/litellm/Dockerfile`:
   ```dockerfile
   RUN pip install --no-cache-dir \
       litellm==<new-version> \
       headroom-ai[all]
   ```
4. Rebuild and restart:
   ```shell
   docker compose -f compose/litellm/docker-compose.yml build
   cove litellm down && cove litellm up
   ```
5. Verify:
   ```shell
   curl http://127.0.0.1:4000/health
   curl http://127.0.0.1:4000/models
   ```
