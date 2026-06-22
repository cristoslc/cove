# Sashay: DNS Infrastructure — DoH Profiles

**PR:** https://git.cove/cristos/cove/pulls/18
**Branch:** `sashay-dns-infrastructure` (exists, has pre-parley work to overwrite)
**Decision:** Parley 2026-06-21 — DoH configuration profiles for all hosts, no relay, no host process, no `/etc/hosts`.

## Chunk 1: Generate and install DoH profile

### Task 1.1: Create `.mobileconfig` template

Create `compose/nginx/config/doh/cove-doh.mobileconfig.j2` — a macOS/iOS configuration profile that configures DNS-over-HTTPS for the `cove` domain.

The profile must:
- Set DoH server URL to `https://127.0.0.1:8053/dns-query` (loopback for dev machine)
- Set domain to `cove` (and `cove.{{ ansible_hostname }}`)
- Include the mkcert root CA so the TLS cert is trusted
- Use a unique PayloadUUID and ProfileUUID (generated at render time, like the iOS DNS profile already does)
- Set `PayloadDisplayName` to "Cove DNS"
- Set `PayloadDescription` to "Resolves *.cove domains via Cove's local DNS-over-HTTPS server"

Reference: the existing iOS DNS profile at `compose/nginx/config/dns/ios.j2` for the UUID generation pattern and Apple plist structure.

### Task 1.2: Add render task to bringup.yml

In `compose/bringup.yml`, add a task in the DNS setup block that:
1. Renders the `.mobileconfig` template to `{{ cove_data_root }}/nginx/config/doh/cove-doh.mobileconfig`
2. Installs it via `sudo profiles -I -F {{ cove_data_root }}/nginx/config/doh/cove-doh.mobileconfig`
3. Only runs on macOS (Darwin)

### Task 1.3: Remove `/etc/hosts` DNS entries

In `compose/bringup.yml`, remove the task that adds `*.cove` hostnames to `/etc/hosts`. The DoH profile replaces this.

Also remove the `/etc/resolver/` file setup — DoH replaces the resolver file too.

### Task 1.4: Remove dnsmasq UDP port mapping

In `compose/docker-compose.yml`, remove the dnsmasq port mapping (`0.0.0.0:5353:5353`). External devices use DoH on port 8053, not UDP DNS on 5353. The dnsmasq container only needs to be reachable internally by dnsproxy.

## Chunk 2: Serve profile for external devices

### Task 2.1: Add profile download to nginx config page

Update `compose/nginx/config.html.j2` to include a link to download the DoH profile for external devices. The link should point to `https://hc.cove:8443/config/doh/cove-doh.mobileconfig` (or the LAN/Tailscale IP equivalent).

### Task 2.2: Serve profile files via nginx

Ensure the nginx config serves static files from `{{ cove_data_root }}/nginx/config/doh/` at the `/config/doh/` URL path. This is already handled by the existing `/config/` location block in the nginx template — verify and add if needed.

## Chunk 3: Update `cove down`

### Task 3.1: Remove DoH profile on teardown

In `cove down` (or a new teardown playbook), add a step to remove the DoH profile:
```bash
sudo profiles -R -p <ProfileUUID>
```

The ProfileUUID should be stored in a known location (e.g., `{{ cove_data_root }}/nginx/config/doh/profile-uuid.txt`) so teardown can find it.

## Chunk 4: Tests

### Task 4.1: Update existing DNS tests

Update `cli/tests/test_e2e_dns.py` to test DoH resolution instead of UDP DNS. The test should:
1. Send a DoH POST to `https://hc.cove:8053/dns-query` for `cove`
2. Verify the response contains the expected A record (127.0.0.1)
3. Test `git.cove`, `vault.cove`, and `*.pages.cove` wildcard

### Task 4.2: Add profile validation test

Add a test that validates the rendered `.mobileconfig` is valid XML with the correct structure.

## Chunk 5: Verification

### Task 5.1: Run full test suite
```bash
uv run --directory cli pytest tests/ -v
```

### Task 5.2: Verify compose config
```bash
docker compose -f compose/docker-compose.yml config --no-interpolate
```

### Task 5.3: Verify DNS resolution
```bash
# Test DoH directly
python3 -c "
import struct, urllib.request, ssl
query = struct.pack('>H', 0x1234) + struct.pack('>H', 0x0100) + struct.pack('>H', 1) + struct.pack('>H', 0) + struct.pack('>H', 0) + struct.pack('>H', 0)
for part in ['cove']:
    query += struct.pack('B', len(part)) + part.encode()
query += struct.pack('B', 0) + struct.pack('>H', 1) + struct.pack('>H', 1)
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
req = urllib.request.Request('https://hc.cove:8053/dns-query', data=query, headers={'Content-Type': 'application/dns-message'}, method='POST')
resp = urllib.request.urlopen(req, context=ctx, timeout=5)
data = resp.read()
ancount = struct.unpack('>H', data[6:8])[0]
print(f'cove -> {ancount} answers')
assert ancount > 0, 'DoH resolution failed'
"
```

### Task 5.4: Verify no `/etc/hosts` entries
```bash
grep -q 'cove' /etc/hosts && echo 'FAIL: hosts entries still present' || echo 'PASS: no hosts entries'
```
