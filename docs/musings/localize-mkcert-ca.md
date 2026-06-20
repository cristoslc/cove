# Musing: Localize mkcert CA to Eliminate $MKCERT_CAROOT Dependency

**Status:** Draft
**Authored-by:** deepseek-v4-flash:cloud
**Date:** 2026-06-19

## The Problem

`compose/docker-compose.yml` line 64 mounts `rootCA.pem` via a variable from `.env`:

```yaml
- ${MKCERT_CAROOT}/rootCA.pem:/certs/rootCA.pem:ro
```

`MKCERT_CAROOT` is an absolute system path (e.g., `/Users/cristos/Library/Application Support/mkcert`) outside `~/Documents/`. `cove up` (via `bringup.yml`) detects it with `mkcert -CAROOT` and writes `.env`. Running `docker compose up` directly (without `cove up`) skips this rendering — `.env` is stale or missing, and the bind mount fails with "not a directory."

## How the Staging Teardown Surface the Issue

The earlier staging teardown cleaned up a worktree (`sashay-dns-infrastructure`) whose compose file was pinned as the active `cove` project:

```
docker compose -p cove ls
# → config file: /Users/cristos/Documents/code/cove/.worktrees/sashay-dns-infrastructure/compose/docker-compose.yml
```

When that container stack was torn down and the correct `compose/docker-compose.yml` was started directly (not via `cove up`), `MKCERT_CAROOT` was unset in the environment.

## Design Principle Violation

The stateless config work established that everything Cove needs should live under `~/Documents/`. `MKCERT_CAROOT` at `/Users/cristos/Library/Application Support/mkcert` violates this — it's an external system path that depends on mkcert being installed, and whose value varies by OS.

## Solution: Copy CA at Deploy Time, Reference Relative Path

Instead of mounting the cert from `$MKCERT_CAROOT` at runtime, have `bringup.yml`:

1. Detect `mkcert -CAROOT` (as it does now)
2. Copy `rootCA.pem` into the compose directory or a predictable path under `COVE_DATA_ROOT`
3. Mount the local copy via a relative path

This eliminates the absolute path dependency from docker-compose.yml entirely.

## Changes Required

### docker-compose.yml

```yaml
# BEFORE:
- ${MKCERT_CAROOT}/rootCA.pem:/certs/rootCA.pem:ro

# AFTER:
- ./certs/rootCA.pem:/certs/rootCA.pem:ro
```

### bringup.yml

Add a task to copy rootCA.pem to `{{ compose_dir }}/certs/rootCA.pem` after reading it (the `slurp` task already reads it — just write it out).

### .env (no change needed, but MKCERT_CAROOT can be dropped)

The `.env` file rendered by bringup.yml currently includes `MKCERT_CAROOT={{ mkcert_caroot_path }}`. Once the compose file no longer references this variable, it can be removed from `.env` — but keeping it is harmless.

## Caveats

- The CA cert changes only when `mkcert -install` is re-run. `bringup.yml` currently re-installs on every `cove up`. This means the cert is always fresh.
- If the cert is updated but no fresh `cove up` runs, nginx serves a stale cert. This edge case already exists today — nothing changes.
- On first `cove up`, the cert must exist. `bringup.yml` handles this by running `mkcert -install` if available.

## Remaining Musings on This Topic

- `cove-default-command-ux.md` — TUI dashboard
- `cove-health-daemon.md` — auto-restart daemon
- `multi-stage-cove.md` — offline issue sync via git-bug