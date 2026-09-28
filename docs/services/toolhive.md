# ToolHive MCP Gateway for Cove

ToolHive is Cove's **MCP gateway** — an optional, profiled service (`profile: mcp`, lifecycle via `cove toolhive up|down|status|logs`) that runs MCP servers as sibling containers on the Cove network, each constrained by a permission profile and explicit mounts. It is the only MCP surface in Cove: LiteLLM's MCP endpoints stay permanently disabled (`disable_mcp: true`, CVE-2026-42271). It mirrors the litellm/speedtest/runner optional-service pattern.

- **Gateway address:** `https://mcp.cove/` (through Cove's nginx ingress; in Phase 1 the vhost serves 403 for everything except `/health` — see Auth Posture). The ToolHive API/UI itself binds `127.0.0.1:${TOOLHIVE_PORT:-8090}` only — never published beyond loopback.
- **Scope:** Phase 1 of [docs/plans/toolhive-mcp-gateway.md](../plans/toolhive-mcp-gateway.md) — control plane, curated registry, ingress, CLI lifecycle. The `cove mcp` data-plane wrapper (Phase 2) and per-project scopes (Phase 3) are not built yet.

## Quick Start

```shell
# Start the gateway (no manual setup needed — the registry and permission
# profile are seeded by `cove up` from bringup.yml):
cove toolhive up
# or start every optional service at once (ToolHive has no credential step,
# so its profile joins the bringup like the runner):
# cove up --all

# Check it's running
cove toolhive status
```

The control plane runs a single `thv serve` container (`cove-toolhive`) with the Docker socket mounted **read-only**; it manages sibling MCP-server containers on the default compose network. Compose owns only the control plane; workloads are created through the ToolHive API.

## Curated registry (IaC)

MCP servers enter the harbor only through the seeded catalog:

- **Source of truth:** [compose/toolhive/registry.json](../../compose/toolhive/registry.json) — upstream MCP registry wire format (`data.servers[]`; the legacy `{"servers": {...}}` shape is rejected by ToolHive v0.51.x). Seeded into `${COVE_DATA_ROOT}/toolhive/registry.json` on first boot and mounted **read-only** into the control plane (`/registry/registry.json`). `thv`'s config points at it via `local_registry_path`; **remote catalog fetch is disabled** (offline-first — no remote registry URL is set).
- **Curated servers (Phase 1):**

| Server | Image (pinned; verified digest) | Posture |
|--------|-------------------------------|---------|
| `io.github.stacklok/filesystem` | `docker.io/mcp/filesystem:1.0.2` (sha256:7030b3d3…) | **Sandboxed — NO mounts by default** |
| `io.github.stacklok/fetch` | `ghcr.io/stackloklabs/gofetch/server:1.0.5` (sha256:e488829d…) | Network-only (outbound fetching is the feature; no mounts) |
| `io.github.stacklok/time` | `ghcr.io/stacklok/dockyard/uvx/mcp-server-time:2026.8.18` (sha256:ab8255cf…) | Sandboxed (no mounts, no outbound) |

  Digests are the multi-arch indexes verified 2026-09-28 against their registries. The filesystem server declares **no read/write mounts** in the seed: granting file access is an explicit runtime decision (declare per-server mounts through the ToolHive API), never a seed default.

- **Default permission profile:** [compose/toolhive/cove-default.json](../../compose/toolhive/cove-default.json) (`cove-sandboxed`) — no read/write mounts, no outbound allow, not privileged. Seeded to `${COVE_DATA_ROOT}/toolhive/profiles/cove-default.json`, mounted read-only at `/profiles`. Mirrors ToolHive's built-in `none` profile. Phase 1 registers no workloads, so the profile is seeded but unused — it is wired for Phase 2 consumption, when `cove mcp` assigns it per server.
- **Adding a server:** edit `compose/toolhive/registry.json` in the repo (pinned image ref, explicit permissions), re-seed, and it exists on every machine. Never register servers ad-hoc in a running container.

## Auth Posture (security)

`mcp.cove` is LAN/Tailscale-reachable (nginx publishes `0.0.0.0:8443`), so the posture is stated, not implicit. As built in Phase 1 (operator ruling on the PR review blocker):

- **Everything on `mcp.cove` returns 403 except `/health`.** Phase 1 has no data-plane consumers, so the vhost exposes none of the ToolHive management API. `cove toolhive status` health-checks through nginx on `/health`; that is the only path that transits the vhost.
- **`/health` is restricted to private-range clients** with the ADE-style allow/deny ACL copied from the `ade.cove` block: loopback, RFC1918 LAN ranges, tailnet CGNAT 100.64/10, container ranges; `deny all` for the public internet.
- **ToolHive UI/API (control plane):** no non-loopback route in Phase 1. The container's own port binding is `127.0.0.1:${TOOLHIVE_PORT:-8090}`, and the nginx vhost 403s every management path. MCP tool calls (Phase 2) will go container-to-container on the compose network.
- **The UI/API route opens in Phase 2**, when data-plane consumers exist — per the plan's guard, behind an auth layer first ([docs/plans/toolhive-mcp-gateway.md](../plans/toolhive-mcp-gateway.md)).

> **Guard:** if a future change exposes the ToolHive UI/API beyond loopback (a `0.0.0.0` host port, a proxied management route, or a second ingress), an auth layer (nginx basic-auth or OIDC) must land first. Guard tests: `test_mcp_block_returns_403_by_default` fails on any proxied path outside `/health`; `test_toolhive_binds_localhost_only` fails on any `0.0.0.0` binding.

## What's Hardened

| Layer | Mitigation |
|-------|-----------|
| **Network** | API/UI binds `127.0.0.1:${TOOLHIVE_PORT:-8090}:8080` only. No `0.0.0.0` host port; the only non-loopback route (nginx at `mcp.cove`) returns 403 for everything except `/health`, which is private-range-ACL'd. |
| **Socket** | `/var/run/docker.sock` mounted **read-only**, control-plane only; container gets the docker gid via `group_add` (Forgejo-runner pattern). Per-MCP-server blast radius is constrained by ToolHive permission profiles and explicit per-server mounts, not by the socket. |
| **Registry** | Curated, IaC-declared, mounted `:ro`; no `:latest` anywhere (every image ref carries a version tag); remote catalog fetch off. |
| **Profiles** | Default profile `cove-sandboxed`: no mounts, no outbound, not privileged. Network-only servers must declare their outbound scope per-server in the registry. |
| **Version** | Pinned to `v0.51.4@sha256:5e1e2536…` (multi-arch index verified 2026-09-28; no `latest`). |
| **Image posture** | Distroless ko image, runs as non-root (uid:gid 1000:1000 by default, overridable at the compose layer). No shell/curl inside — the compose healthcheck runs the bundled `thv list`, which discovers the API and verifies `/health` with the startup nonce. |
| **Memory** | Memory-limited (`TOOLHIVE_MEM_LIMIT`, 512M default). |
| **Data** | All state under `${COVE_DATA_ROOT}/toolhive/` (config, state, profiles, registry) per the Data in Documents rule. |
| **LiteLLM** | `disable_mcp: true` stays permanent (CVE-2026-42271) with a cross-reference comment; guard test `TestLitellmMcpGuard` enforces it. |

## Configuration

Data lives at `~/Documents/cove-data/toolhive/`. The `.env` is written by `cove up` from `bringup.yml` (first boot): `TOOLHIVE_IMAGE`, `TOOLHIVE_CONTAINER_NAME`, `TOOLHIVE_PORT`, `TOOLHIVE_MEM_LIMIT`. Secrets are **not** wired in Phase 1 — per-server credentials come via ToolHive's secrets store seeded from Vault in Phase 2; nothing is hardcoded in registry.json.

## What it does NOT do

- No `cove mcp add/remove/list` data-plane wrapper yet (Phase 2).
- No per-project MCP scopes or per-project mounts (Phase 3).
- No Vault-backed per-server secret wiring (Phase 2).
- No OIDC/IdP or virtual-MCP workflow features (single-dev posture).
- No remote catalog fetch (offline-first).
- Does not re-enable LiteLLM MCP endpoints — ever.

## Lifecycle

- `cove toolhive up` — start (uses `--profile mcp`, does not touch core services).
- `cove toolhive down` — stop (uses `stop`, preserves workload data).
- `cove toolhive status` — check through nginx on `mcp.cove` via 8443 (`/health`).
- `cove toolhive logs` — tail logs.
- `cove up --all` — starts the `mcp` profile along with the other optional services (no credential step needed before the bringup starts it).