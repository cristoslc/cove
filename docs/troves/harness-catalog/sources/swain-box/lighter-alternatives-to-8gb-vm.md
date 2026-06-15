# Lighter alternatives to 8GiB Lima VM

The current VM is specced at 4 CPU / 8GiB RAM, which is heavy for what's actually running inside: opencode server + Caddy. What would lighter options look like?

## 1. Shrink the Lima VM (✅ Done — now at 4GiB)

Real measurement (June 2026): `opencode serve` uses ~1.31 GiB RSS, Caddy ~34 MiB. Ubuntu 24.04 idle ~300MB. So total VM footprint is ~1.7 GiB. Dropped from 8GiB → 4GiB — plenty of headroom for OS cache and burst. Could likely go to 2GiB without issue, but 4GiB is safe.

## 2. Ditch the VM entirely — opencode serve on macOS

- Run `opencode serve` as a launchd plist on the host
- Caddy same machine, binds `:4097`
- No virtualization overhead, no mount complexity
- Downside: no kernel isolation. If opencode is compromised, it has host filesystem access.

## 3. Docker container (on host)

- A `Dockerfile` with opencode + Caddy in a single container or compose stack
- Still runs on host kernel, but containers offer some isolation
- Simpler than Lima, widely understood
- Downside: Docker Desktop on macOS is itself a VM — adds overhead without the same isolation guarantees

## 4. Lima with Docker inside (Colima pattern)

Use Lima to run Docker, then opencode in a container inside the VM. Extra layer but clean separation of VM infra from app.

## 5. Lighter guest OS in Lima

Alpine Linux instead of Ubuntu — ~50MB idle. But must verify opencode supports it (static binary? musl compat?). Also fewer packages if provisioning ever needs debugging tools.

## 6. OrbStack

macOS-native Docker/VM replacement, lighter than Docker Desktop. Can run Lima VMs too (as an alternative vz backend?). Not FOSS.

## Open questions

- ~~What does opencode `serve` actually consume in steady state? Haven't measured.~~ Measured — 1.31 GiB RSS.
- Is kernel isolation a hard requirement or a nice-to-have?
- If sacrifice isolation, what's the deployment story for the MCP filesystem server (currently `npx` inside VM)?
- ccusage data read path: currently reads from host mount of `~/lima-opencode-data/`. Any alternative needs same data access.