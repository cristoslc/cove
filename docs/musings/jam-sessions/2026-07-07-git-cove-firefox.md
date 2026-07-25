# Jam: git.cove won't load in Firefox

## 2026-07-07 — Initial diagnosis

- **Symptom:** `https://git.cove/` loads in Safari and curl, but not Firefox
- **DNS:** Resolves to `127.0.0.1` correctly in Firefox (TRR=false)
- **HAR analysis:** TLS handshake succeeds (`_securityState: "secure"`), but HTTP response status is 0 — connection established, no response received
- **Certs:** nginx still serves mkcert-signed certs (not Cove-generated). mkcert CA is in macOS system keychain. Cove Root CA exists at `~/.config/cove/pki/` but not installed in system trust store.
- **Hypothesis:** Surfshark VPN extension in Firefox intercepts localhost-bound traffic after TLS handshake
- **Root cause:** Surfshark VPN extension intercepts `127.0.0.1` traffic after TLS handshake
- **Fix:** Disable Surfshark extension for `git.cove` or localhost
- **Also:** Installed mkcert CA into both Firefox NSS profiles (`nrq5zq92.default`, `x0mxp5rz.default-release`) so certs validate in Firefox even without system trust store
- **Note:** nginx still serves mkcert-signed certs, not Cove-generated ones — the mkcert-to-Cove migration (PR #33) hasn't been deployed yet
