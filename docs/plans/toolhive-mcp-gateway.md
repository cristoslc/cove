# Plan: ToolHive as the Cove MCP Gateway at `mcp.cove`

Source thread: bb thread `thr_ge6en4f4cw` (evaluate ToolHive for Cove's MCP gateway). Builds on `docs/musings/mcp-isolation-and-dynamic-mounts.md` (two-layer mount architecture) and `docs/musings/cove-cli-service-vs-data-plane.md` (`cove toolhive` service plane, `cove mcp` data plane).

## Problem

Cove has no MCP path at all. LiteLLM's MCP endpoints are deliberately disabled (`disable_mcp: true`, CVE-2026-42271) and must stay that way. Agentic tools in the harbor (ADE/bb harness) have no way to consume MCP servers without running them ad-hoc on the host, which violates the harbor principle and the isolation model in the MCP musing.

Decision made (this thread): adopt **ToolHive** as the MCP service layer, deployed as an **optional profiled service** at `https://mcp.cove/`, mirroring the litellm/speedtest/runner pattern. LiteLLM's `disable_mcp: true` stays permanent.

## Why ToolHive (decision record)

- Apache 2.0, single-binary Go platform, no SaaS dependency, self-hostable registry. Rugpull-safe (enhancement layer, not foundation).
- Ships the exact architecture the MCP musing converged on: one container per MCP server, per-server permission files, explicit bind mounts, hot-reloadable via the ToolHive API, trust tiers (sandboxed/network-only vs. code-access).
- Answers the musing's open question 1 (supply-chain risk on MCP server dependencies) with containerization + permission profiles.
- Superior to the LiteLLM MCP gateway: LiteLLM spawns stdio MCP servers inside the LiteLLM container (shared process space, mounts, provider keys), its MCP surface just shipped a command-injection CVE, and Cove has no keys or teams to benefit from its per-key tool scoping.

## Design decisions

- **Optional service pattern** (mirrors litellm/speedtest/runner): compose service gated by `profiles: ["mcp"]`, lifecycle via `cove toolhive up|down|status|logs`.
- **Deployment shape**: ToolHive control plane (`thv`) runs as a container with `/var/run/docker.sock` bind-mounted **read-only**, managing sibling MCP-server containers on the default compose network. Same socket-mount pattern the Forgejo runner already uses. The `thv` runtime creates MCP server containers outside compose; compose only owns the control plane. The socket is control-plane only: blast radius per MCP server is constrained by ToolHive permission profiles and explicit per-server mounts, not by the socket mount itself.
- **Image**: pinned ToolHive container image (verify current tag and digest at implementation; pin by digest, not `latest`).
- **State/data**: `${COVE_DATA_ROOT}/toolhive/` (ToolHive state, logs, registry cache) per the Data in Documents rule. The `thv` sibling containers keep their data in the same root via mounts declared in the seeded config.
- **Network**: ToolHive API/UI binds `127.0.0.1:${TOOLHIVE_PORT:-8090}:8080` only, reachable through nginx. MCP servers themselves publish no host ports; they join the compose network so harbor consumers reach them at `http://<server>:<port>` directly, and the gateway endpoint proxies streamable HTTP.
- **Ingress**: nginx server block `mcp.cove` + `mcp.cove.local` in `default.conf.j2` (rendered artifact — edit the template only), variable upstream (`set $toolhive_upstream http://toolhive:8080;` — the container port on the compose network, since nginx is inside it; the host loopback binding stays `127.0.0.1:${TOOLHIVE_PORT:-8090}`) so nginx starts when the profile is off, same pattern as the litellm block. Add `proxy_http_version 1.1`, `proxy_set_header Upgrade`/`Connection` and long read timeouts for streamable HTTP/SSE.
- **Registry is IaC**: a seeded, versioned `compose/toolhive/registry.json` (curated catalog: pinned server images, default permission profiles, default mounts) mounted read-only into the toolhive container. Remote catalog fetch disabled by default (offline-first). New MCP servers enter the harbor only through this file.
- **Secrets**: MCP server credentials injected via ToolHive's secrets store, seeded from Vault through the existing `cove creds vault-get` flow into the compose `.env` (the litellm/speedtest pattern). Never hardcoded in registry.json; env-var-only credential passing (litellm service posture).
- **Permission posture**: default profile is sandboxed (no code mounts, network only). Code-accessing servers (filesystem, git) require explicit mounts declared per-server in registry.json. No per-project mounts in phase 1 (the `cove project` surface does not exist yet); per-project scoping is phase 3, per the musing's hybrid model.
- **Auth posture (explicit)**: `mcp.cove` is LAN/Tailscale-reachable, so the posture must be stated, not implicit. Follow the ADE precedent (ADR-018): the Cove network is the trust boundary; MCP tool-call endpoints are unauthenticated by design. The ToolHive UI/API (control plane) must NOT be exposed at the same URL unrestricted: bind the UI/API to loopback only and either omit the UI route entirely in phase 1 or gate the UI path with nginx basic-auth. **Phase-1 ruling (sashay review, as built):** Phase 1 has no data-plane consumers, so the vhost returns 403 for everything except `/health` (which is proxied with a private-range ACL); the basic-auth option was ruled out and the UI/API route opens in Phase 2 behind an auth layer. Guard: if a future change exposes the UI/API beyond loopback, it requires an auth layer first. `cove toolhive status` health-checks through nginx like speedtest does.
- **LiteLLM stays MCP-free**: keep `disable_mcp: true`; the existing guard tests in `test_litellm.py` stay green. Add a comment cross-referencing this plan so nobody "helpfully" re-enables it.

## Implementation steps

1. **compose/toolhive/**: `registry.json` seed (start with 2–3 curated servers, e.g. filesystem sandboxed, fetch/network-only; pins verified at implementation), default permission profile file, nginx template block, Dockerfile if a build step is needed.
2. **compose/docker-compose.yml**: add `toolhive` service, `profiles: ["mcp"]`, socket mount (ro), `127.0.0.1` port binding, health check on the API root, memory limit, pinned image.
3. **compose/nginx/default.conf.j2**: `mcp.cove` server block (variable upstream, WS/SSE headers).
4. **compose/bringup.yml**: render/seed the registry, `.env` defaults (`TOOLHIVE_PORT`, mem limit), wire into `cove up --all` so the credentials-first ordering holds.
5. **cli/cove/toolhive.py**: service-plane group `up|down|status|logs`, mirroring `speedtest.py`; register in `cli.py`.
6. **Tests** (`cli/tests/test_toolhive.py`, mirroring `test_litellm.py`): pinned image + digest, socket mount is read-only, `127.0.0.1` binding, profile name, UI/API not exposed beyond loopback, registry.json parses and contains no unpinned image refs, nginx template block present, `disable_mcp` guard still true.
7. **Docs**: `docs/services/toolhive.md` following `speedtest.md` structure (quick start, auth posture, what's hardened, lifecycle); AGENTS.md bullet; entry in `docs/test-coverage-matrix.yaml`.
8. **Staging**: isolated-profile e2e via `scripts/staging/` (deploy with `--profile mcp`, health-check `mcp.cove` through 9443, teardown).

## Phasing

- **Phase 1 (this plan)**: toolhive service + gateway at `mcp.cove`, seeded registry, CLI lifecycle, tests, docs.
- **Phase 2**: `cove mcp add/remove/list` data-plane wrapper over the ToolHive API; Vault-backed secret wiring per server.
- **Phase 3**: per-project MCP scopes (`cove project up` mounts project-scoped servers) once the `cove project` surface lands; trust levels (trusted/sandboxed/custom) layered on registry entries.

## What it does NOT do

- No Kubernetes operator, OIDC/IdP, or virtual-MCP workflow features (single-dev posture).
- No re-enabling of LiteLLM MCP endpoints.
- No MCP server state outside `~/Documents/cove-data/`.
- No remote catalog fetch by default.
