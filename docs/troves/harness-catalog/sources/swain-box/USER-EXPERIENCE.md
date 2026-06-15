# USER-EXPERIENCE.md

## Installation and onboarding

1. Install Lima: `brew install lima`
2. Place `~/.lima/opencode-dev.yaml`
3. Create data dir: `mkdir -p ~/lima-opencode-data`
4. Start VM: `limactl start opencode-dev`
5. Caddy + opencode start automatically (or manually via shell)

## Quality attributes

- **Latency**: opencode API reachable at `http://localhost:4097` — no perceptible overhead vs bare metal
- **Isolation**: VM provides separate kernel; no process-level escape possible
- **Portability**: Same config works on macOS and Linux; swap only `vmType`

## UX principles

- "One command to start" — `limactl start opencode-dev` brings up everything
- "Read the host config, write to a known mount" — no config duplication
- "Portable by design" — Lima YAML + Caddyfile + opencode.jsonc travel together

See `docs/user-experience/` for full detail.