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
