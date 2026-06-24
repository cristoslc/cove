# Plan: DNS Foundation — dnsmasq + /etc/resolver/cove

**Branch:** `sashay-dns-foundation` (new, off `main` @ `5186912`)
**Supersedes:** PR #32 (closed — DoH-primary approach rejected)
**Architecture:** `docs/musings/cove-dns-architecture.md`

## Scope

Replace `/etc/hosts` lineinfile with dnsmasq as the DNS foundation + `/etc/resolver/cove` for local resolution. Drop DoH profile machinery entirely. Salvage the non-DoH improvements from the closed branch.

## Changes

### 1. Remove `/etc/hosts` lineinfile from bringup.yml

Delete the "Add *.cove hostnames to /etc/hosts" task (lines ~180-187 in `compose/bringup.yml` and the synced `cli/cove/resources/compose/bringup.yml`). This is the sudo friction source and the static-entry limitation.

### 2. Publish dnsmasq `:5353` on `0.0.0.0`

In `compose/docker-compose.yml` (and `cli/cove/resources/compose/docker-compose.yml`), add back the dnsmasq port mapping that the DoH branch removed:

```yaml
dnsmasq:
  ports:
    - "0.0.0.0:${DNSMASQ_PORT:-5353}:5353"
```

This makes dnsmasq reachable from loopback (local), LAN, and Tailscale (remote). Same `0.0.0.0` exposure as `:443` — accepted for now per `cove-up-sudo-friction.md`.

### 3. Install `/etc/resolver/cove` on macOS (one-time, detect-and-skip)

Add a task in `bringup.yml` (Darwin only):
- Check if `/etc/resolver/cove` exists and points at `127.0.0.1:5353`.
- If not, create it (needs `become: true` — one-time, not per-`cove up`).
- If yes, skip.
- Content: `nameserver 127.0.0.1\nport 5353`

This is the local resolution path. Verified working today on this machine.

### 4. Salvage `linux.j2` rewrite

From the closed branch: `linux.j2` was rewritten to use systemd-resolved DoH config. Update it to point at `host_ip:5353` (standard DNS) as primary, DoH as optional. Sync to `cli/cove/resources/compose/nginx/config/dns/linux.j2`.

### 5. Salvage `ios.j2` ServerURL fix

The branch fixed `ios.j2` ServerURL. Keep the fix but be honest about the DoH-on-iOS situation: profile works when installable, manual IP access is the fallback. Sync to cli copy.

### 6. Salvage `config.html.j2` updates

The branch updated the config landing page. Salvage the non-DoH-specific parts. Sync to cli copy.

### 7. `macos.j2` — resolver instructions, not DoH

Rewrite `macos.j2` to instruct creating `/etc/resolver/cove` pointing at `host_ip:5353` (for remote Macs) or `127.0.0.1:5353` (for dev machine). No DoH profile instructions. Sync to cli copy.

### 8. `cove down` — resolver teardown

Salvage the teardown structure from the branch. `cove down` removes `/etc/resolver/cove` if it was created by Cove (detect via content match, not blind delete). No DoH profile removal.

### 9. Salvage staging script improvements

`scripts/staging/deploy.sh` and `scripts/staging/e2e.sh` had improvements on the branch. Salvage if they're independent of DoH.

### 10. Tests

- Remove DoH profile tests (74 tests on the branch).
- Add `/etc/resolver/cove` install tests: verify task creates file when absent, skips when present.
- Add dnsmasq `:5353` publish test: verify port mapping in compose.
- Update E2E DNS tests: verify `*.cove` resolves via dnsmasq on `:5353`, not via DoH.
- Keep `cove down` teardown tests (adapt for resolver removal).

## Out of scope

- DoH profile template (`.mobileconfig`) — dropped entirely.
- dnsproxy `:8053` publish — DoH is not primary. (dnsproxy container can stay internal for optional DoH; no port publish.)
- `:443` port collapse — separate sashay per `cove-up-sudo-friction.md`.
- iOS DoH profile install — documented as a gap in the architecture musing; not solved here.
- AGENTS.md test-command/E2E declarations — separate governance decision.

## Sashay steps

1. Create worktree `.worktrees/sashay-dns-foundation`, branch off `main`.
2. Implement changes 1-10.
3. Run tests: `uv run --directory cli pytest tests/ -q`.
4. Staging E2E: deploy, verify `*.cove` resolves via dnsmasq, verify `/etc/resolver/cove` installed, teardown.
5. Code review.
6. Chronicle + PR.