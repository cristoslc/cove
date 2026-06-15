# TECH-STACK.md

## Host

- **OS**: macOS (primary), Linux (target)
- **Hypervisor**: Apple Virtualization.framework (`vz`) on macOS, QEMU on Linux
- **Container/VM runtime**: Lima (v1.x+)

## VM Guest (Linux)

- **OS**: Ubuntu 24.04 LTS (Lima default)
- **Reverse proxy**: Caddy 2
- **AI server**: opencode

## Toolchain

- **Package manager**: Homebrew (macOS host), apt (VM guest)
- **VM management**: `limactl`
- **Usage tracking**: ccusage (`bunx ccusage opencode`)

See `docs/tech-stack/` for full detail.