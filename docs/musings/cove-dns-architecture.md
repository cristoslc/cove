# Cove DNS Architecture

**Status:** Musing — major architectural question. Not ready for sashay.
**Supersedes:** [`drop-etc-hosts.md`](drop-etc-hosts.md) (which scoped too narrow — this musing subsumes it).

## The question

How should Cove provide DNS resolution for `*.cove` across every device class — local and remote, every OS — in a way that is composable (works for more than one Cove instance), shareable (new devices join without per-device setup), maintainable (no per-OS install ceremony that breaks on OS updates), and **offline-first** (works without any third-party service that could rugpull)?

This is a major piece of Cove. The wrong answer creates ongoing per-device friction, breaks on OS updates, couples Cove to a single-device model, or builds on a third-party service as foundational infrastructure.

## Constraints (from PURPOSE.md + operator)

1. **Offline by default.** "If it needs the internet to work, it is not done." DNS must work on a plane.
2. **Self-contained.** "Cove requires exactly three things from the host: Python, uv, and a container runtime. Everything else — services, certificates, DNS, runners — is brought and managed by Cove." DNS is Cove's responsibility, not a third party's.
3. **No third-party as foundational infrastructure.** Tailscale is useful for remote access, but Cove MUST NOT build on it as a load-bearing dependency. A Tailscale rugpull (pricing change, account lockout, API deprecation, free-tier restriction) must not break Cove's DNS. Tailscale is an enhancement layer, not the foundation.
4. **One address, everywhere.** The FQDN is the same online and offline. What changes is how the name resolves. PURPOSE.md names `/etc/hosts` + dnsmasq as the offline path and MagicDNS as the online path — but MagicDNS is an enhancement, not a requirement.
5. **Single developer, possibly multiple devices.** The operator accesses Cove from a phone, a laptop, maybe a second Mac. Not single-machine, but single-owner.

## What we've tried and where it broke

### Iteration 1: `/etc/hosts` lineinfile (original)

Cove's original bringup appended `127.0.0.1 git.cove vault.cove ...` to `/etc/hosts` on the dev machine. Worked. But:
- Only handled the dev machine. Remote devices needed manual hosts edits.
- Required sudo (`become: true`) every `cove up`.
- Ephemeral across reboots (not technically, but Ansible didn't manage it cleanly).
- Static — only knew about services hardcoded in the lineinfile. New Cove services needed new entries.

### Iteration 2: `/etc/resolver/cove` + dnsmasq (pre-DoH branch)

`/etc/resolver/cove` pointing at `127.0.0.1:5353`, dnsmasq container answering for `*.cove` with a wildcard. Better:
- Wildcard resolution — new services just work.
- Still dev-machine-only. Remote devices still needed manual config.
- Still needs root to write `/etc/resolver/`.
- dnsmasq published `:5353` to host. Colima ssh mux binds it as user — no sudo for the bind.

Verified working right now (Jun 24): `/etc/resolver/cove` on this machine resolves `git.cove` correctly via dnsmasq-on-TCP (mDNSResponder falls back to TCP when UDP gets no response).

### Iteration 3: DoH profiles (current branch, `sashay-dns-infrastructure`)

The DoH branch replaced `/etc/hosts` and `/etc/resolver` with per-OS DNS profiles served by nginx at `/config/dns/{macos,ios,linux,windows,android}.j2` + a shared DoH `.mobileconfig` for Apple platforms. The intent was: every device downloads its profile, installs it, and gets encrypted DNS resolution for `*.cove` via `https://ts_ip:8443/dns-query`.

**This broke in several ways:**

1. **macOS 26.1 regression:** Apple broke manual installation of `com.apple.dnsSettings.managed` profiles. The system treats DNS Settings payloads as VPN payloads and fails to create the Network Extension. Affects every DoH provider (Mullvad, NextDNS, AdGuard), not just Cove. MDM-installed profiles also fail (Jamf Now confirms same error on managed Macs). No workaround — Apple bug.

2. **iOS DoH silently broken:** `ios.j2` hardcodes `ServerURL: https://{{ ts_ip }}:443/dns-query`, but nginx publishes `:8443` and the pf `rdr` redirect is loopback-only. An iOS device on the tailnet hits `ts_ip:443`, which goes nowhere. The `:443` port collapse (per `cove-up-sudo-friction.md`) would fix this, but it hasn't shipped yet.

3. **WSL has no template at all.** WSL has its own resolver (`/etc/resolv.conf` proxying to Windows DNS, or systemd-resolved if the distro has systemd). Completely unaddressed.

4. **Per-device install ceremony.** Even when DoH worked, every device needed to: download profile, install it, trust the root CA. That's ceremony per device, per Cove instance. If you run two Coves (work + personal), you need two profiles. If a profile breaks on an OS update, every device re-installs.

5. **DoH is an enhancement, not a foundation.** DoH encrypts DNS in transit. But on loopback (`127.0.0.1:5353`), DNS never leaves the machine — encryption is meaningless. On a tailnet, Tailscale already encrypts all traffic including DNS queries. DoH solves a problem (plaintext DNS over untrusted networks) that Cove's own network topology already avoids. It's overhead solving a non-problem.

### What the DoH branch got right

- **dnsmasq as the authoritative source for `*.cove`.** A container running dnsmasq, answering wildcard DNS for the Cove namespace, is the right primitive. It's self-contained, offline-first, composable (different Cove instances use different hostname suffixes), and not coupled to any third party.
- **Linux** uses systemd-resolved DoH config (`linux.j2`). Works, composable, no per-device ceremony beyond running the script.
- **Windows** uses hosts file (`windows.j2`). Ugly, but Windows doesn't support DoH profiles natively and hosts file is the universal Windows answer.
- **Android** points at Tailscale MagicDNS as the primary path (`android.j2`). Acceptable as an enhancement — Android's Private DNS setting is the fallback.

## The architecture question, reframed

The DoH branch asked: *"How does each device class install a DNS profile?"*

The right question is: **"What's the minimal DNS infrastructure that Cove owns, that works offline, that remote devices can reach when a network is available, and that doesn't depend on a third party as foundational?"**

### The answer: dnsmasq is the foundation

Cove runs a dnsmasq container. It answers `*.cove` (wildcard, or `*.cove.{{ hostname }}` for multi-instance). It's the authoritative source for the Cove namespace. Everything else is a question of how devices reach it.

**Local (dev machine):** `/etc/resolver/cove` → `127.0.0.1:5353`. One-time root install of the resolver file. dnsmasq publishes `:5353` on loopback. Works offline, no third party, no per-`cove up` ceremony. This is what's running today.

**Remote (any device, any OS):** dnsmasq publishes `:5353` on `0.0.0.0`. Any device that can reach the host's IP (via Tailscale, LAN, VPN, whatever) can query `*.cove` directly at `host_ip:5353`. The device's own resolver needs to know to route `*.cove` queries there — and that's where the per-OS question lives. But the key insight is: **the DNS server is the same regardless of OS.** Only the client-side routing differs.

### The client-side routing matrix (honest version)

This is where it gets ugly, and where there's no single answer that avoids per-OS ceremony. The question is: how does each OS route `*.cove` queries to Cove's dnsmasq?

| Platform | Local (dev machine) | Remote (other device) | Mechanism | Ceremony |
|-----------|---------------------|------------------------|-----------|----------|
| **macOS** | `/etc/resolver/cove` | `/etc/resolver/cove` (pointed at host IP, not loopback) | Native macOS per-domain resolver | One-time root write to `/etc/resolver/` |
| **iOS** | n/a | DoH profile (`/config/doh/`) **OR** Tailscale Split DNS | iOS has no `/etc/resolver` equivalent | Per-device profile install (when DoH works) or Tailscale admin config |
| **Linux** | systemd-resolved or `/etc/resolv.conf` | systemd-resolved or `/etc/resolv.conf` | Native Linux resolver config | One-time config write |
| **Windows** | hosts file | hosts file | No native per-domain resolver | Per-device hosts edit |
| **Android** | n/a | Private DNS setting or Tailscale | Android system DNS config | Per-device settings change |
| **WSL** | `/etc/resolv.conf` (inherits Windows) | `/etc/resolv.conf` | Linux resolver inside WSL | One-time config write |

**The honest assessment:** there is no zero-ceremony path for remote devices that doesn't depend on a third party (Tailscale Split DNS would be zero-ceremony but it's rejected as foundational). The choice is: **per-device ceremony** (install resolver config on each device) vs **third-party dependency** (Tailscale handles it). Cove's principles say: per-device ceremony, because third-party rugpull is worse than ceremony.

### What about composable — multiple Cove instances?

Each Cove instance uses a different hostname suffix: `cove.{{ hostname }}`. dnsmasq answers for `*.cove.{{ hostname }}`. Devices that need to reach multiple Coves have multiple resolver entries — `/etc/resolver/cove.work` and `/etc/resolver/cove.personal`, for example. This is composable without a registry: the namespace itself encodes the identity.

### What about a shareable registry?

The operator asked about a "shareable registry." The honest answer: **dnsmasq IS the registry.** It's a running service that answers "what IP does `git.cove.foo` resolve to?" for any device that asks. The question is how devices discover that dnsmasq exists and how they route queries to it.

Options for discovery:
1. **Cove serves instructions at `/config/dns/`.** The current approach — nginx serves per-OS setup scripts. New device visits `https://cove_ip/config/`, picks its OS, runs the script. This is what the DoH branch already does (minus the DoH profile install). It's self-documenting and offline-first.
2. **Cove CLI on the dev machine prints setup instructions.** `cove dns` could print "to add a device, visit https://cove_ip/config/ or run this command." Useful for the operator but doesn't help a friend you're sharing a page with.
3. **A mDNS/Bonjour announcement.** Cove's dnsmasq could announce itself via mDNS as `cove-dns._udp.local`. macOS and Linux devices on the LAN could discover it automatically. But mDNS is LAN-only, doesn't help Tailscale/remote, and iOS/Android don't support mDNS-based DNS resolver discovery. Interesting but incomplete.

Option 1 (the current approach, minus DoH) is the most Cove-aligned: self-documenting, offline, no third party, per-device ceremony but guided.

## Proposed architecture

**Foundation: dnsmasq container, authoritative for `*.cove.{{ hostname }}`.**

- dnsmasq publishes `:5353` on `0.0.0.0` (reachable from loopback, LAN, Tailscale — wherever the host is reachable).
- dnsmasq answers wildcard `*.cove.{{ hostname }}` → `127.0.0.1` (local) or `host_ip` (remote). The template already handles this via `ts_ip` / LAN IP facts.

**Local path (dev machine): `/etc/resolver/cove.{{ hostname }}`**

- Points at `127.0.0.1:5353`.
- One-time install (needs root). `cove up` detects if present and skips if so — no per-run sudo.
- Works offline. No third party. Already verified working.

**Remote path: per-OS resolver config, guided by `/config/dns/`**

- `macos.j2` — instructions to create `/etc/resolver/cove.{{ hostname }}` pointing at `host_ip:5353` (not loopback). One-time per remote Mac.
- `linux.j2` — systemd-resolved config pointing at `host_ip:5353`. One-time per remote Linux.
- `windows.j2` — hosts file entries (Windows has no per-domain resolver). Per-device.
- `android.j2` — Private DNS setting or manual DNS per Wi-Fi network.
- `ios.j2` — **honest about the gap.** iOS has no `/etc/resolver` equivalent and DoH profiles are broken on macOS 26 (though iOS itself may still work — the bug is macOS-specific). If DoH works on the iOS version, serve the profile. If not, the only path is Tailscale (enhancement, not foundation) or manual IP access (`https://host_ip:8443`). Be honest that iOS is the weakest platform here.
- `unknown.j2` — fallback instructions.

**Drop entirely:**

- DoH profile render+install in `bringup.yml` (the `open`-based install that breaks on macOS 26).
- `cove down` profile removal (no profile to remove).
- The `.mobileconfig` template as the primary macOS path. Keep it as an *optional* path for iOS / macOS versions where it still works, but don't rely on it.

**Keep as optional:**

- dnsproxy + nginx `/dns-query` route. DoH is an enhancement for devices that want encrypted DNS over untrusted networks. Not the foundation. Keep the server, drop the per-OS profile install ceremony.

**Tailscale as enhancement, not foundation:**

- If the operator uses Tailscale, Cove works better — `ts_ip` is reachable from anywhere, and the operator *can* configure Tailscale Split DNS for zero-ceremony remote resolution. But Cove doesn't require it, doesn't depend on it, and works fully offline without it.
- `android.j2` already treats MagicDNS as the primary path for Android — that's fine, because Android has Private DNS as a fallback that doesn't need Tailscale.

**What this eliminates:**
- The broken macOS DoH profile install (and the `open` vs `profiles -I` macOS-26 workaround).
- The per-device profile install ceremony as a *requirement* (it becomes per-device resolver config, which is simpler and more stable).
- Coupling to Apple's DNS Settings payload, which Apple can and does break.
- Coupling to Tailscale as foundational infrastructure.

**What this requires:**
- dnsmasq publishing `:5353` on `0.0.0.0` (currently internal-only after the DoH branch removed the port mapping).
- `/etc/resolver/cove.{{ hostname }}` install task in `bringup.yml` (one-time, needs root, detect-and-skip if present).
- Rewritten `macos.j2` — resolver file instructions, not DoH profile.
- Honest `ios.j2` — DoH profile if it works, manual IP access if it doesn't.
- `linux.j2` updated to point at `host_ip:5353` (standard DNS, not DoH) as the primary path, DoH as optional.

## The honest gaps

1. **iOS is the weakest platform.** No `/etc/resolver` equivalent. DoH profiles work today but broke on macOS 26 (and could break on iOS in a future update). Without Tailscale, the only fallback is manual IP access (`https://host_ip:8443`). There's no self-contained, offline-first, zero-ceremony DNS path for iOS. This is an Apple platform limitation, not a Cove design flaw — but it's real.

2. **Windows is ugly.** Hosts file is the only per-domain mechanism without third-party tools. No wildcard support — every Cove service needs a separate hosts entry. `windows.j2` currently hardcodes `git.cove` and `vault.cove` — adding new services means updating the script. Could be improved by having the script query dnsmasq and populate entries dynamically, but that's complexity.

3. **Per-device ceremony is unavoidable without a third party.** Every remote device needs some one-time configuration to route `*.cove` queries to Cove's dnsmasq. The ceremony is minimal (one resolver file or one hosts entry) and guided (Cove serves instructions), but it's there. The alternative is Tailscale Split DNS (zero ceremony, but third-party dependency). Cove's principles chose ceremony over dependency.

4. **`0.0.0.0:5353` exposure.** Publishing dnsmasq on all interfaces means anyone on the LAN can enumerate `*.cove`. Not sensitive (the answers are local IPs), but it's information leakage. Same exposure question as `:443` in `cove-up-sudo-friction.md` — defer LAN-blocking, accept `0.0.0.0` for now.

## Open questions

1. **iOS path:** Accept manual IP access as the fallback, or invest in keeping DoH profiles working on iOS (separate from macOS)? The macOS 26 bug is macOS-specific; iOS may still install profiles fine. But for how long?

2. **Windows wildcards:** Keep the static hosts-file approach (simple, but new services need script updates), or have `windows.j2` dynamically query dnsmasq and populate entries? The latter is more composable but adds complexity.

3. **mDNS discovery:** Is it worth having dnsmasq announce itself via mDNS (`cove-dns._udp.local`) so macOS/Linux devices on the LAN can discover it without visiting `/config/`? Interesting but incomplete (iOS/Android/WSL don't support it) and adds a service.

4. **DoH as second-class citizen:** Keep dnsproxy + nginx `/dns-query` as an optional encrypted path, or remove it entirely? Keeping it means maintenance for a path that's no longer primary. Removing it means no encrypted DNS for devices on untrusted networks (though Tailscale, when present, already encrypts).

5. **The `drop-etc-hosts.md` vNext plan:** Superseded by this musing. DoH is no longer the answer; dnsmasq + per-OS resolver config is.

## Decision needed

- Adopt dnsmasq as foundation, `/etc/resolver/cove` as local path, per-OS resolver config as remote path, drop DoH profiles as primary?
- Accept the iOS gap (manual IP access as fallback)?
- Rework the DoH branch accordingly, or close it and open a new one?

## See also

- [`drop-etc-hosts.md`](drop-etc-hosts.md) — superseded by this musing.
- [`cove-up-sudo-friction.md`](cove-up-sudo-friction.md) — `:443` port collapse, same `0.0.0.0` exposure question.
- [`PURPOSE.md`](../../PURPOSE.md) — Offline by Default, Self-Contained, One Address Everywhere.