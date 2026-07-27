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

## Open Questions

1. **What's the actual threat model?** If I'm the only user and I control which MCP servers I install, is parent-dir mounting acceptable? The risk is supply-chain attacks on MCP server dependencies, not malicious intent.

2. **Should we separate MCP servers by trust level?** A `filesystem` MCP server from a verified publisher is different from a random `npx` package. Maybe the MCP VM has multiple mount profiles: `trusted` (full code access), `sandboxed` (no code access, network only), `custom` (explicit mounts).

3. **Does the Colima VM restart cost matter?** Adding a mount requires `colima stop mcp && colima start mcp` — ~10-15 seconds. Is that acceptable per project? Or do we need hot-reloadable mounts?

4. **What about Docker-in-Docker?** If the MCP VM runs Docker, and each MCP server is in its own container within the VM, we could mount selectively per-container. But that adds complexity.

5. **Is there a middle ground?** Mount `~/Documents/code/` read-only, and only specific project dirs read-write? Most MCP tools need read access to understand project structure, but write access is rarer.

## Next Thoughts

The cleanest path might be:
1. Start with parent-dir mount (`~/Documents/code/`) — it's what we'd do manually anyway
2. Add a `cove mcp trust` / `cove mcp sandbox` command to classify MCP servers
3. Trusted servers get the full mount; sandboxed servers get network-only
4. If a specific project needs isolation, add a `cove mcp isolate <project>` that excludes it from the mount

This gives us the zero-config experience by default with an escape hatch for sensitive projects.
