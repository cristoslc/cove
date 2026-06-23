# Cove Up Sudo Friction

**Status:** Reframed (parley, 2026-06-23). Original framing was wrong — see below.

## Original framing (wrong)

`cove up` prompts for sudo every time, and after every reboot the pf rules are gone so you have to run it again. Treated as two separate problems: (1) pf rules don't survive reboot, (2) multiple sudo prompts per run. Proposed fixes: auto-install sudoers, LaunchDaemon for pf persistence, or move pf into a container.

**That framing treated a symptom, not the cause.**

## The actual problem: host-side ephemeral state, introduced by a port-ownership conflict

Investigation during parley surfaced the real chain:

1. `ai-chatbot-caddy` (a stale stack that should have been torn down) was squatting `0.0.0.0:443` on the host — including `127.0.0.1`.
2. Cove's nginx publishes `0.0.0.0:8443:443` (per `docker-compose.yml:69`), not `:443`, because `:443` was already taken.
3. To give Cove the standard port on loopback anyway, `bringup.yml:189-203` installs a pf `rdr` rule on `lo0`: `127.0.0.1:443 → 127.0.0.1:8443`.
4. That pf rule requires `become: true` (host root), which is what drags sudo into every `cove up`.
5. pf rules are kernel-ephemeral — gone after reboot — which is why `cove up` has to run again after every reboot to reinstall the anchor.

So the sudo friction and the reboot-persistence bug are **the same problem**: a host-side pf redirect exists only because another stack claimed `:443` first. Remove the conflict and the pf rule, the sudo dependency, and the reboot requirement all disappear together.

## What Colima is actually doing (verified)

Colima uses an ssh-based port forwarder (`portForwarder: ssh`, `network.mode: shared`). The ssh mux process (`~/.colima/_lima/colima/ssh.sock [mux]`) runs as the user and binds Docker's published ports on the host as the user — no host sudo needed for the bind itself. Confirmed by `lsof`: pid 9447 (`cristos`, not root) listens on `:8443`, `:8080`, `:5353`, etc. A throwaway `docker run -p 443:80 nginx:alpine` succeeded once `ai-chatbot-caddy` was stopped — **Colima can publish `:443` directly as the user, no sudo, no pf.**

This also means: the cove-sudoers file at `compose/files/cove-sudoers` (granting `NOPASSWD: ALL`) is solving a problem that won't exist once the port conflict is resolved. On this machine it was already installed at `/etc/sudoers.d/cove`, which masked the friction rather than fixing it. Retire the sudoers file, don't auto-install it.

## The fix

Three changes, in order:

1. **Tear down `ai-chatbot`** (operator-confirmed: it should already have been torn down). This frees `:443` on the host.
2. **Switch Cove's nginx publish to `0.0.0.0:443:443`** in `docker-compose.yml` (drop the `:8443` publish entirely — two ports was a holdover from the conflict era). Bind to `:443` directly.
3. **Delete the two `become: true` tasks in `bringup.yml`** — the `/etc/hosts` lineinfile (lines 180-187) and the pf redirect (lines 189-203). Neither is needed once Cove owns `:443` and `/etc/hosts` is replaced by DoH.

After this, the only remaining host-side ephemeral state is the `/etc/hosts` line — which is already specced for elimination by DoH in [`drop-etc-hosts.md`](drop-etc-hosts.md). Once DoH lands, `cove up` after reboot becomes unnecessary: Colima's LaunchAgent autostarts the VM, `restart: unless-stopped` brings the containers back, nginx serves `:443` directly, DoH resolves `*.cove`. Nothing for `cove up` to do.

## Future: blocking LAN without losing Tailscale + localhost

The "for now" decision is `0.0.0.0:443:443` — Cove is reachable from LAN and Tailscale on the standard port. The eventual requirement is to block LAN while keeping Tailscale + localhost. Three paths, deferred:

- **Tailscale serve** (ADR-013, superseded by ADR-014). ADR-014's rationale was about *local* ingress (nginx vs Caddy/Traefik), not remote exposure. The supersession may have been premature on the remote-exposure axis. Reopen when LAN-blocking becomes real.
- **IP-specific Docker binds** (`127.0.0.1:443:443` + `100.x.x.x:443:443`). Hardcodes a host-specific Tailscale IP into compose config — exactly the host-side state this reframe is trying to eliminate.
- **pf allow-list on host** — reintroduces the pf-reboot-persistence problem we just escaped. Reject.

Not deciding now. Note that ADR-013's supersession didn't fully settle the remote-exposure question.

## What was rejected (and why)

- **Auto-install `NOPASSWD: ALL` sudoers (Option A in the original musing).** Throwaway work — solves a problem that disappears with the port fix. Also: `NOPASSWD: ALL` is broader than needed and a security regression on a machine that runs browsers, npm installs, MCP servers, etc. The file already exists as documentation; leave it as documentation.
- **LaunchDaemon for pf persistence (Option B).** Throwaway — the pf rule itself is going away.
- **"Move pf to the VM."** Wrong layer: the conflict pf was resolving is on the host (between two host-side listeners), not in the VM. By the time traffic reaches the VM it's already been claimed by whichever container bound `:443` first.
- **Keeping `:8443` alongside `:443`.** Two ports was a holdover from the conflict era. Once Cove owns `:443`, `:8443` has no audience — Tailscale clients were hitting `:8443` only because `:443` was unavailable. Worth verifying no bookmarks/remotes on other devices point at `:8443` before the collapse, but the target is a single port.

## Open verification before implementation

- Confirm no other devices have `git.cove:8443` (or any `*.cove:8443`) baked into bookmarks, git remotes, or config. The port collapse will silently break those (connection refused, not redirected).

## See also

- [`drop-etc-hosts.md`](drop-etc-hosts.md) — DoH eliminates the remaining `/etc/hosts` ephemeral state.
- [`cove-health-daemon.md`](cove-health-daemon.md) — orthogonal; addresses observability, not sudo/persistence.
- ADR-014 (nginx as sole ingress) — local ingress decision; remote-exposure angle (ADR-013's territory) remains deferred.