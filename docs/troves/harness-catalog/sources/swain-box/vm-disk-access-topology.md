# VM disk access topology

Current mounts in `opencode-dev.yaml`:

| Host path | VM mount point | Writable |
|---|---|---|
| `~/.config/opencode` | `/home/user.linux/.config/opencode` | No |
| `~/lima-opencode-data` | `/home/user.linux/.local/share/opencode` | Yes |
| `~/projects` | `/home/user.linux/projects` | Yes |

Missing mounts that the server or attach sessions might need:

## Source code directories

- **`~/code/`** — where most repos live (cove, swain-box, dispatch-opencode-skill, etc.). Currently not mounted. If the VM needs to serve these via MCP filesystem, they need to be accessible.
- **`~/projects/`** — already mounted. Good.

## Agent harness configs

- **`~/.agents/`** — skills, memories, AGENTS.md detail files. Currently not mounted. The server reads these for agent instructions.
- **`~/.claude/`** — Claude-specific config (skills, etc.). Not mounted.
- **`~/.opencode/`** — opencode config. Not mounted (though `~/.config/opencode` is).

## Config directories

- **`~/.config/opencode/`** — already mounted (ro). Covers opencode.jsonc, MCP configs, Caddyfile.
- **`~/.config/` subdirs for other tools** — probably not needed in the VM.

## Answers (June 2026)

1. ✅ Server reads `~/.agents/` and `~/.claude/` at **runtime**. Many sessions share the same server, and config should be hot-reloadable (no restart needed).
2. `~/code/` should be mounted so the MCP filesystem can serve repos there.
3. `~/.opencode/` was deprecated; `~/.config/opencode/` is the canonical path (already mounted ro).
4. ✅ Writable mounts for code dirs are desired — opencode edits files in the working directory.

## Mount plan

```
~/.agents/           → /home/user.linux/.agents          (ro) — skills, memories, AGENTS detail
~/.claude/           → /home/user.linux/.claude           (ro) — Claude skills
~/Documents/code/    → /home/user.linux/Documents/code    (rw) — source repos (cove, skills, etc.)
~/.config/opencode/  → /home/user.linux/.config/opencode  (ro) — already done
~/lima-opencode-data/ → /home/user.linux/.local/share/opencode (rw) — already done
~/Documents/projects/ → /home/user.linux/Documents/projects (rw) — already done
```
