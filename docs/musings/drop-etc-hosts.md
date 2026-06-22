# Drop `/etc/hosts` — DNS-over-HTTPS for all hosts

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
