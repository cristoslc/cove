# Cove Up Sudo Friction

`cove up` prompts for sudo every time, and after every reboot the pf rules are gone so you have to run it again. Two separate problems that compound.

## Problem 1: pf rules don't survive reboot

macOS pf rules configured via `pfctl` are ephemeral — they vanish on reboot. The `bringup.yml` playbook sets up a `rdr` (redirect) rule to forward `:443` → `:8443` (or whatever `nginx_https_port` is). After reboot, that rule is gone.

So every reboot requires `cove up` with sudo to reinstall the pf anchor. This is the "needs manual cove up after every reboot" part.

**Options:**
- Ship a LaunchDaemon (`/Library/LaunchDaemons/cove.pf.plist`) that runs `pfctl -f /etc/pf.anchors/cove` on boot. This would make the pf rule persistent without any manual step.
- Document that `cove up` is needed after reboot (current state, but the user finds it annoying).
- Move off pf entirely — use macOS's `socat` or a userspace proxy (HAProxy in the compose stack?) to avoid needing root for port forwarding at all.

## Problem 2: Multiple sudo prompts per run

The user reports being asked for sudo password multiple times in a single `cove up` run. The code analysis shows only 1 Ansible `-K` prompt (for `bringup.yml`), but there are additional vectors:

1. **Ansible `-K` prompt** — one password prompt for the `bringup.yml` playbook's `become: true` tasks.
2. **DNS config scripts** — if the user visits the nginx config page and runs the DNS setup script, those scripts self-elevate with `exec sudo bash "$0"`.
3. **`mkcert -install`** — runs as user but may prompt on some systems.

If the user is running `cove up` without `--no-sudo`, they get at least 1 prompt. If they also need to run DNS setup separately, that's another. The "multiple times" complaint might also be that Ansible's `-K` prompt is easy to mistype, and there's no retry logic — you have to restart the whole `cove up`.

## The fix that already exists: passwordless sudo

There's a `cove-sudoers` file at `cli/cove/resources/compose/files/cove-sudoers` that grants `NOPASSWD: ALL` to a specified user. It's never auto-installed.

**What's missing:**
- No `cove up` flag or interactive prompt to install it.
- No detection of whether it's already installed.
- The template requires manual editing (`YOUR_USERNAME` placeholder).
- It grants `NOPASSWD: ALL` which is broad but arguably fine for a single-user dev machine.

## What to do

Three approaches, not mutually exclusive:

### A. Auto-install sudoers on first `cove up`

Add a step to `bringup.yml` (or a new playbook) that:
1. Detects the current user.
2. Checks if `/etc/sudoers.d/cove` exists and is valid.
3. If not, writes it with `NOPASSWD: ALL` for the current user.
4. Validates with `visudo -c`.

This would require sudo on the *first* run (to create the sudoers file), but all subsequent runs would be passwordless. The first-run sudo prompt is unavoidable, but it's a one-time cost.

### B. LaunchDaemon for pf persistence

Ship a `.plist` that loads the pf anchor at boot. This eliminates the "must run cove up after reboot" requirement for the pf rule. The `/etc/hosts` entries would still need to be re-applied after reboot (they're also ephemeral in some configurations), but that's a lighter-weight operation.

### C. Eliminate the need for sudo entirely

- Replace `pfctl` with a userspace proxy (e.g., `socat` in a Docker container that binds `:443` and forwards to the nginx container). Docker can bind privileged ports without sudo on macOS because Docker Desktop/Colima runs as root in the VM.
- Replace `/etc/hosts` editing with a local DNS resolver (dnsmasq already runs in the compose stack — point the system at it). The DNS resolver scripts already exist but require manual setup.

This is the cleanest long-term solution but requires more work.

## Recommendation

Short-term: **Auto-install the sudoers file** on first `cove up`. This eliminates the "multiple prompts" complaint with minimal code. The pf reboot problem remains but is a separate concern.

Medium-term: **Ship a LaunchDaemon** for pf persistence, or **move pf into a container** to eliminate the root dependency entirely.

See also: [`cove-health-daemon.md`](cove-health-daemon.md) — a health daemon could also handle pf rule re-application on detection of failure.
