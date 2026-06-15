# ARCHITECTURE.md

## System context

The host (macOS or Linux) runs a Lima VM containing opencode server and Caddy reverse proxy. The VM provides kernel isolation while sharing config (read-only) and data (write from VM, read from host) via 9p/virtiofs mounts.

## Containers

| Container | Tech | Notes |
|---|---|---|
| Lima VM | Lima (Apple VZ / QEMU) | Kernel isolation boundary |
| Caddy | Caddy 2 | Reverse proxy, binds `:4097` → `127.0.0.1:8848` |
| opencode server | opencode `serve` | Listens `127.0.0.1:8848` |
| ccusage (host) | ccusage `bunx` | Reads DB from host mount, read-only |

## Mount topology

- `~/.agents/` → VM (ro) — skills, memories, AGENTS detail files
- `~/.claude/` → VM (ro) — Claude skills
- `~/.config/opencode/` → VM (ro) — config, AGENTS.md, MCP defs
- `~/Documents/code/` → VM (rw) — source repos (cove, skills, etc.)
- `~/Documents/projects/` → VM (rw) — working directories
- `~/lima-opencode-data/` → VM (rw) — opencode SQLite DB, sessions

## C4

See `docs/architecture/` for C4 context, container, and component diagrams.

## DDD bounded contexts

| Context | Responsibility |
|---|---|
| VM Orchestration | Lima lifecycle, provisioning, networking |
| Proxy | TLS termination, host→guest routing |
| Server | opencode API, session management, MCP dispatch |
| Observability | ccusage aggregation, log collection |