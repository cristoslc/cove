# Drop `/etc/hosts` — DNS-over-HTTPS for all hosts

**Status:** Superseded by [`cove-dns-architecture.md`](cove-dns-architecture.md). DoH profiles are no longer the primary path — macOS 26 broke `.mobileconfig` install, and the architecture reframe established dnsmasq + per-OS resolver config as the foundation. Kept for historical context.

## The problem

`cove up` writes entries to `/etc/hosts` so `git.cove`, `vault.cove`, etc. resolve on the
development machine. This works but has persistent side effects — the file accumulates
entries across runs, cleanup on `cove down` is unreliable, and every `cove up` needs
`sudo`. Worse, `/etc/hosts` has no wildcard support, so `*.pages.cove` and
`{service}.{project}.cove` are impossible to manage.

The root cause: **Colima with Virtualization.Framework does not forward UDP ports**.
macOS's system resolver speaks UDP/TCP, but any DNS server inside a container is
unreachable via UDP from the host.

## The solution: DoH configuration profiles

macOS 14+ supports DNS-over-HTTPS natively via configuration profiles (`.mobileconfig`).
The container's dnsproxy already terminates DoH on port 8053 (confirmed working —
valid DNS wire-format POST to `https://hc.cove:8053/dns-query` returns correct answers).

The stack:

```
macOS resolver (DoH) → https://127.0.0.1:8053/dns-query → container dnsproxy → dnsmasq
```

No relay, no host process, no `/etc/hosts`, no UDP. The entire chain is TCP-based and
works through Colima's port forwarding.

## Cross-platform

| Platform | Mechanism | Notes |
|---|---|---|
| **macOS** | `.mobileconfig` profile | Native DoH support since macOS 14 |
| **iOS** | `.mobileconfig` profile | Same profile, different server URL (LAN/Tailscale IP) |
| **Android** | Private DNS (DoT) | Or DoH via `dnsproxy` app |
| **Windows 11** | Native DoH | Per-adapter DNS over HTTPS setting |
| **Linux** | `systemd-resolved` | `resolvectl` with DoH server URL |

The container's dnsproxy serves all of them. External devices use the cove machine's
LAN or Tailscale IP instead of `127.0.0.1`.

## Impact on bounded contexts

| Context | Responsibility |
|---|---|
| **Container orchestration** | dnsmasq + dnsproxy inside Colima |
| **Platform integration** | Install DoH profile on each device |
| **DNS resolution** | System resolver (DoH) → container dnsproxy → dnsmasq |

No platform adapter process needed. The DoH profile is a configuration artifact, not a
running service.

## Trade-offs

**For:**
- No `/etc/hosts` side effects
- No `sudo` for DNS (profile install is one-time, can be scripted)
- No persistent process on the host
- Wildcard DNS works (`*.pages.cove`, `{service}.{project}.cove`)
- Same mechanism works for external devices (phone, tablet, laptop)
- DoH is encrypted (privacy on untrusted networks)

**Against:**
- Profile install requires `sudo` (one-time, not per-run)
- Loopback DoH URL (`https://127.0.0.1:8053/dns-query`) — macOS may reject it
  (fallback: use LAN or Tailscale IP)
- Slightly more latency than direct kernel lookup (TLS handshake per query, or
  persistent connection)
- dnsproxy's TLS cert must be trusted by the device (mkcert CA)

## Implementation sketch

1. Expose dnsproxy's HTTPS port to the host (already done — `8053:8053`)
2. Generate a `.mobileconfig` profile for macOS/iOS with:
   - DoH server URL: `https://127.0.0.1:8053/dns-query` (or LAN/Tailscale IP)
   - Domain: `cove` (and `cove.{{ ansible_hostname }}`)
   - TLS trust: embed mkcert root CA
3. Install the profile via `sudo profiles -I -F cove-doh.mobileconfig`
4. Remove `/etc/hosts` entries
5. For external devices, serve the profile from the nginx config page

## Decision (parley, 2026-06-21)

**vNext implements DoH for all hosts, including localhost.** No relay, no host process,
no `/etc/hosts`. The container's dnsproxy is the single DoH endpoint for the entire
cove mesh.

## macOS 26 profile installation problem

macOS 26 (Sequoia) removed `profiles -I` for CLI-based profile installation. Profiles
must be installed via System Settings (GUI) or MDM. The `cove up` playbook's install
task fails silently (`failed_when: false`).

### Options

| Option | Automation | User friction | Wildcard support | Notes |
|---|---|---|---|---|
| **Keep `/etc/hosts`** | Full (`sudo`) | None | No | Works, needs sudo per run, no `*.pages.cove` |
| **`open` .mobileconfig** | Semi (opens dialog) | One click | Yes | `open cove-doh.mobileconfig` triggers System Settings |
| **Local dnsproxy relay** | Full (one-time `sudo`) | None | Yes | launchd plist, UDP:5353 → DoH → container |
| **Custom onboarding page** | None | Manual steps | Yes | Guide user through System Settings |
| **`/etc/resolver/` + local dnsproxy** | Full (one-time `sudo`) | None | Yes | Resolver points to local dnsproxy on UDP:5353 |

### Recommendation

`open` is the right fix — one click, no `sudo`, no persistent daemon, no attack surface.
The relay was a solution to a problem (`profiles -I` being available) that macOS 26
removed. `open` is simpler, safer, and better in every dimension.

### Implementation sketch

In `compose/bringup.yml`, replace the `profiles -I` task with:

```yaml
- name: Open DoH profile for installation
  when: ansible_system == "Darwin"
  ansible.builtin.command:
    argv:
      - open
      - "{{ cove_data_root }}/nginx/config/doh/cove-doh.mobileconfig"
  changed_when: false
  failed_when: false

- name: Remind user to install profile
  when: ansible_system == "Darwin"
  ansible.builtin.debug:
    msg: |
      DoH profile opened in System Settings.
      Click Install to enable *.cove DNS resolution.
      Alternatively, install manually from:
        https://hc.cove:8443/config/doh/cove-doh.mobileconfig
```
