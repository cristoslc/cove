# MCP Isolation: Dynamic Mounts Across Many Projects

## The Problem

We want to run MCP servers in an isolated Colima VM (the `mcp` profile). MCP servers like `filesystem`, `github`, `playwright`, etc. need access to specific directories. But which directories?

The naive approach: mount `~/Documents/code/` into the MCP VM so any project is accessible. But this defeats the purpose of isolation — now the MCP VM has access to *everything* in your code directory, including projects with secrets, SSH keys in `.ssh/`, cloud credentials in `.aws/`, etc.

## The Dynamic Mount Challenge

Projects are created, moved, and deleted regularly. A static mount list in `colima.yaml` would need constant manual updates. We'd need something like:

- Mount at the parent-dir level (e.g., `~/Documents/code/`) — simple but broad
- Mount per-project with a daemon that watches for new projects — complex but precise
- Mount nothing by default, require explicit opt-in per project — most secure but highest friction

## Parent-Dir Mount: The Tradeoffs

Mounting `~/Documents/code/` into the MCP VM:

**Pros:**
- Zero configuration — any new project is immediately accessible
- No daemon or watcher needed
- Works with existing workflows (create project, start using MCP tools on it)

**Cons:**
- All projects are visible to all MCP servers — a compromised `filesystem` MCP server can read every project
- If any project contains credentials (`.env`, service account keys, etc.), they're exposed
- The MCP VM's blast radius includes your entire development corpus
- Hard to audit — you can't easily tell which MCP server accessed which project

## Alternative: Per-Project Opt-In

A more disciplined approach:

- MCP VM starts with no code mounts
- A CLI tool (`cove mcp mount <project>`) adds a mount and restarts the MCP VM
- A config file (`~/.config/cove/mcp-mounts.yaml`) tracks the active set
- On `cove up`, the MCP VM is configured with the current mount list

**Pros:**
- Explicit — you know exactly what's exposed
- Auditable — the mount list is a config file
- Minimal blast radius — only projects you explicitly mount

**Cons:**
- Friction — every new project requires a command
- Forgetting to mount a project means MCP tools don't work on it
- Need a daemon or hook to auto-mount common patterns (e.g., the current project)

## Hybrid: Parent-Dir with Selective Submounts

What if we mount `~/Documents/code/` but use MCP-level access controls?

- The VM sees the full tree (for filesystem operations that need parent context)
- But each MCP server gets a restricted view via MCP middleware or tool-level permissions
- LiteLLM's MCP gateway supports per-key/team tool access — could extend to per-tool directory scoping

This is the most flexible but requires MCP middleware that doesn't fully exist yet.

## The Homelab Pattern vs. Cove Pattern

Homelab solves this differently: MCP servers run on a **separate host** with no access to the development machine's filesystem at all. MCP tools that need local context (filesystem, git) are simply not available remotely. The MCP servers that *are* available (web search, weather, etc.) don't need local files.

Cove is different — it's a local development platform. The whole point is that MCP servers *should* be able to interact with local projects. So we can't just say "no local access."

## The Hot-Reload Requirement

Multiple swarms may be running simultaneously. A Colima VM restart kills all running swarms — unacceptable. So VM-level mounts must be set once at boot and never change. Mount changes must happen at the container level, which is hot-reloadable (just `docker compose up -d`).

## The Two-Layer Mount Architecture

This reframes the problem entirely:

```
Host (~/Documents/code/)
  └── Colima VM "mcp" (broad VM-level mount of ~/Documents/code/)
        ├── Container: filesystem-server (bind mount: project-a/, project-b/)
        ├── Container: github-server    (bind mount: project-a/.git/)
        ├── Container: playwright-server (no code mount)
        └── Container: db-server        (bind mount: project-b/data/)
```

**Layer 1 — VM level (set at boot, never changes):**
- Mount `~/Documents/code/` into the Colima VM
- This is the "parent-dir" mount — broad, set once
- The VM sees everything, but no process inside the VM sees it by default

**Layer 2 — Container level (hot-reloadable, per-server):**
- Each MCP server runs in its own Docker container within the VM
- Each container gets explicit bind mounts to only the projects it needs
- Adding a project to a server is `docker compose up -d <server>` — no VM restart
- Multiple swarms coexist; each has its own set of containers with their own mounts

### Why This Works

- **Hot-reloadable**: Container-level mounts are instantaneous — no VM restart
- **Per-server granularity**: A `filesystem` server gets project mounts; a `weather` server gets none
- **Per-swarm isolation**: Each swarm's servers are independent containers; restarting one doesn't affect others
- **VM restart is rare**: Only when the Colima VM itself needs updating (kernel, Docker engine, resource reallocation)

### The Threat Model Shifts

The VM-level mount is still broad, but the blast radius is now **per-container**:
- A compromised `weather` server has no code access — it's network-only
- A compromised `filesystem` server can only read the projects explicitly mounted to it
- The VM itself is the isolation boundary — if the VM is compromised, everything is exposed, but that's the same as any VM-based isolation

This is acceptable for a single-user homelab: the VM is trusted infrastructure; the containers are the untrusted surface.

## Implementation Sketch

```yaml
# ~/.config/cove/mcp-servers.yaml
servers:
  filesystem:
    image: ghcr.io/.../mcp-filesystem
    mounts:
      - project-a
      - project-b
    resources:
      cpus: 0.5
      memory: 256m

  github:
    image: ghcr.io/.../mcp-github
    mounts:
      - project-a
    env:
      GITHUB_TOKEN: "@cove:secrets/github-token"

  weather:
    image: ghcr.io/.../mcp-weather
    mounts: []  # no code access
```

A `cove mcp mount <project> --server <server>` command updates the config and runs `docker compose up -d <server>` — no VM restart, no swarm disruption.

## Colima VM Lifecycle

Colima auto-checks for updates on `colima start` but doesn't auto-update. The MCP VM would need periodic `colima stop mcp && colima upgrade mcp`. This could be automated in `cove up` (check version, prompt to upgrade) or a background health daemon. Not a burden — Colima releases are infrequent and upgrades are fast (~30s).

## Central vs. Per-Project MetaMCP

Two competing architectures:

### Central MetaMCP (one aggregator, always running)

```
MCP VM
  └── MetaMCP (always up, no mounts)
        ├── filesystem-server (mounts: project-a, project-b)
        ├── github-server    (mounts: project-a)
        └── weather-server   (no mounts)
```

- Simple — one MetaMCP instance, all servers registered
- Servers are always consuming resources even when no project is active
- Mount list grows over time as projects accumulate
- Server restarts affect all projects simultaneously

### Per-Project MetaMCP (project-scoped, starts/stops with project)

```
MCP VM
  ├── MetaMCP-project-a (started by `cove project up .` in project-a/)
  │     ├── filesystem-server (mounts: project-a/)
  │     └── github-server    (mounts: project-a/)
  │
  └── MetaMCP-project-b (started by `cove project up .` in project-b/)
        ├── filesystem-server (mounts: project-b/)
        └── db-server        (mounts: project-b/data/)
```

- Each project gets its own MetaMCP + server containers
- Starts on `cove project up .`, stops on teardown
- Zero resource consumption when project is inactive
- Perfect isolation — project-a's servers can't see project-b's files
- Mounts are trivially scoped to the project directory
- Maps naturally to Cove's existing project model

### The Case for Per-Project

Cove already has `cove project up` / `cove project down`. Adding MCP servers as project-scoped containers is a natural extension — the project's `cove.yaml` (or equivalent) declares which MCP servers it needs, and `cove project up` starts them alongside the project's other services.

The central MetaMCP model is better for always-on servers (weather, web search, etc.) that aren't project-specific. These could live in a separate "global" MetaMCP instance that's always running.

**Hybrid approach:**
- One global MetaMCP for always-on, non-project servers (weather, web search, etc.)
- Per-project MetaMCP instances for project-scoped servers (filesystem, github, db, etc.)
- The global MetaMCP can also serve as a fallback — if a project doesn't declare its own servers, it gets the global set

This gives us the best of both: always-on utility servers + project-scoped isolation for code-accessing servers.

### DNS Naming

```
mcp.cove.local              ──> global MetaMCP (always-on utility servers)
{project}.mcp.cove.local    ──> per-project MetaMCP (project-scoped servers)
mcp.cove.{hostname}         ──> global MetaMCP from tailnet
{project}.mcp.cove.{hostname} ──> per-project MetaMCP from tailnet
```

The MCP Colima VM exposes ports via `--network-address` or port forwarding. Nginx on the host routes `*.mcp.cove` to the MCP VM's MetaMCP endpoints. Each per-project MetaMCP gets a dynamic port on the VM; nginx routes by subdomain.

```
Host nginx
  mcp.cove.local              ──> MCP VM :12000 ──> global MetaMCP
  project-a.mcp.cove.local    ──> MCP VM :12001 ──> project-a MetaMCP
  project-b.mcp.cove.local    ──> MCP VM :12002 ──> project-b MetaMCP
```

Port allocation is dynamic — `cove project up` assigns the next available port and registers the route with nginx (or the MCP VM's internal reverse proxy). This integrates with the existing Cove DNS pattern (dnsmasq wildcard `*.cove` + nginx regex server blocks).

## Open Questions

1. **What's the actual threat model?** If I'm the only user and I control which MCP servers I install, is parent-dir mounting acceptable? The risk is supply-chain attacks on MCP server dependencies, not malicious intent.

2. **Should we separate MCP servers by trust level?** A `filesystem` MCP server from a verified publisher is different from a random `npx` package. Maybe the MCP VM has multiple mount profiles: `trusted` (full code access), `sandboxed` (no code access, network only), `custom` (explicit mounts).

3. **Does the Colima VM restart cost matter?** With the two-layer architecture, VM restarts are rare (only for VM updates). Container-level mount changes are hot-reloadable. The restart cost is no longer a concern.

4. **What about Docker-in-Docker?** Not needed — the Colima VM *is* the Docker host. Containers within it bind-mount from the VM's persistent host mount. This is standard Docker, not DinD.

5. **Is there a middle ground?** Mount `~/Documents/code/` read-only at the VM level, and only specific project dirs read-write at the container level. Most MCP tools need read access to understand project structure, but write access is rarer.

6. **How does MetaMCP fit?** MetaMCP would run as a container in the MCP VM, acting as the aggregator. It doesn't need code mounts itself — it just proxies to the per-server containers that have the mounts. This keeps MetaMCP's own attack surface minimal.

## Next Thoughts

The two-layer architecture solves the hot-reload problem cleanly. The path forward:
1. Create the `mcp` Colima profile with a broad VM-level mount of `~/Documents/code/`
2. Run MetaMCP as a container in the MCP VM (no code mounts)
3. Each MCP server is a separate container with explicit project bind mounts
4. `cove mcp` CLI commands manage the server config and hot-reload individual containers
5. Trust levels can be layered on top: `trusted` servers get their requested mounts; `sandboxed` servers get network-only; `custom` servers get explicit mounts from the user
