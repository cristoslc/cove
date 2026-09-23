# Tunnel (zrok2 managed relay) for Cove

`cove tunnel` publishes a `.cove` service to the **public web** through a zrok.io managed relay (zrok2, free tier). It is an **optional, profiled** sidecar (`profile: tunnel`) — the default stack has zero zrok references, and everything works offline without it.

The client is a single sidecar container (`openziti/zrok2`, pinned) running the zrok2 CLI. It is **outbound-only**: no published ports, no inbound exposure, no VPS, no port-forwarding. Shares are **closed by default** — a share exists only while `cove tunnel up` keeps it active.

## Onboarding journey (one-time)

1. **Sign up at [myzrok.io](https://myzrok.io/)** (no credit card required) and copy your **account token** from the console.
2. **Store the token** in 1Password under the shared `Zrok Account` item (ADR-017 conventions), keyed so it is reused across machines:
   ```shell
   cove creds vault-put 'op://Private/Zrok Account/account_token'
   ```
   `cove tunnel` reads it via `cove creds vault-get`. You can also set `ZROK_ACCOUNT_TOKEN` in the compose `.env` or your shell — that value is honored directly. If no token is found anywhere, the command **fails loudly** with setup instructions (never an anonymous fallback).
3. **Run `cove tunnel up`** — the sidecar starts, and the first `up` runs `zrok2 enable <token>` idempotently (state persists in `${COVE_DATA_ROOT}/tunnel/`, mounted at `/home/ziggy/.zrok2`).

## Usage

```shell
# Interactive picker (arrow keys): choose from Cove's discovered services
cove tunnel up
# → picker lists e.g. `git — https://git.cove.local`, Enter selects

# Service shorthand — resolves the name against Cove's nginx ingress config
cove tunnel up git
# → https://<random>.share.zrok.io (or the reserved name below)

# Explicit URL — the power escape hatch
cove tunnel up https://git.cove.local

# Share with a stable reserved name
cove tunnel up git --public myforge
# → https://myforge.share.zrok.io  (name survives restarts)

# Private share — no public URL at all; the other side pulls with a token
cove tunnel up --private
# → zrok2 access private <token>  (from a second environment)
```

`cove tunnel up` **blocks** while the share is active (Ctrl-C or `cove tunnel down` tears it down). `cove tunnel ls` lists active shares; `cove tunnel down [NAME]` releases a named share (removing its rendered route) or stops the sidecar.

### Service picker — no silent default

Bare `cove tunnel up` never picks a service for you. It presents an interactive
picker (arrow keys, Enter; `q` cancels) of the services Cove discovers from its
**nginx ingress config** — every proxied vhost in `compose/nginx/default.conf`
(git.cove → forgejo, vault.cove → vault, litellm.cove, speedtest.cove, the
landing root, pages). Each entry shows the resolved target. Regex-only vhosts
(`*.pages.cove`), redirects (ca.cove), and health endpoints are not tunnelable
and are excluded.

When stdin is not a TTY, the bare form **fails loudly** listing the available
services and their targets — it never falls back to a default. An unknown
shorthand fails the same way. There is no `DEFAULT_TARGET` anymore.

### Cove renders the public-share nginx routes

The operator never writes nginx blocks. When a share is created, Cove renders
a server block for `<name>.share.zrok.io` into `compose/nginx/cove-tunnel-shares.conf`
(mounted into nginx and included from `default.conf`), routes it to the
selected service's upstream with `Host: $host` preserved, and reloads nginx
(validating with `nginx -t` first; on rejection the previous include is
restored). `cove tunnel down` removes the rendered route. Share state lives in
`COVE_TUNNEL_SHARES` in the compose `.env`; the rendered file is a pure
artifact of that state (IaC: bringup seeds an empty file so the bind-mount is
never wedged as a directory). TLS for the public hop terminates at the zrok
relay edge, so the internal hop needs no public-name certificate.

### Targets and tunnel-to-ingress

Picker/shorthand shares route through the ingress — the same path a local
visitor takes — with the `Host:` header preserved, so Forgejo/Vault/etc. see
their own identity. The tunnel is a **pipe**: no URL rewriting, no `sub_filter`.
The app's identity (`ROOT_URL` etc.) stays with the app. Explicit-URL shares
pass the URL through to zrok2 unchanged; HTTPS targets with Cove's self-signed
certs are shared with `--insecure` (the hop never leaves the machine).

### Reserved names (zrok2 v2 conventions)

zrok2 v2 renamed the v1 verbs: `zrok reserve`/`zrok share reserved` are gone. Instead:

- `zrok2 create name <name>` — reserve a stable name (lowercase alphanumeric, 4–32 chars; enforced by `cove tunnel --public`).
- `zrok2 share public <target> -n public:<name> --headless` — share under that name.
- Public URLs live under **`share.zrok.io`** (the v2 public namespace), one flat level — `<name>.share.zrok.io`.
- `zrok2 modify name -r <name>` promotes an ephemeral name in place ("this share earned a permanent name").

`--public` reserves the name for the session; the share's nginx route is rendered by Cove for as long as the share is active.

### Private shares

`cove tunnel up --private` creates a private share reachable **only** over the OpenZiti overlay: the other environment runs `zrok2 access private <token>`. No public URL exists at all — the closest match to Cove's closed-by-default posture.

## Cost ladder

| Tier | Cost | Notes |
|---|---|---|
| **zrok.io free (this feature)** | $0 | Reserved names, private shares, token auth, 5 GB/day, 25 environments, 50 backends. No card required. |
| localhost.run free (fallback) | $0 | Zero-account fallback: random names only, no auth. |
| localhost.run custom domain | $9/mo | Stable `lhr.rocks` subdomain or own domain. |
| Cheap VPS bastion | ~$3–4/mo | `ssh -R` or self-hosted relay; your domain, your TLS. |

## The interstitial-page caveat

Unverified free zrok accounts get an **anti-phishing interstitial page** the first time anyone visits each public share URL. Adding a credit card to the myzrok account (anytime, verification-only) removes it. This is the known cost of the free tier; document it when sharing a demo link.

## localhost.run fallback

If you want zero accounts, zero tokens, and don't need a stable name:

```shell
ssh -R 80:127.0.0.1:8443 nokey@localhost.run
```

Random subdomains only, no auth story, no reserved names — which is why zrok2 is the default and localhost.run is the documented fallback.

## Security posture

| Layer | Posture |
|---|---|
| **Network** | Outbound-only sidecar; no published ports. Reaches the ingress over the compose network and zrok.io over TLS. |
| **Auth** | Account-scoped shares; the account token lives in 1Password (`Zrok Account` item) + Vault + compose `.env` (0600). Missing token = loud failure. |
| **Shares** | Closed by default: exist only while `cove tunnel up` is active. Reserved names persist, shares do not auto-restart. |
| **Version** | Image pinned by digest (`openziti/zrok2:2.0.4`). |
| **Container** | `read_only: true`, tmpfs scratch, non-root user, memory-limited (256M). |
| **Data** | `${COVE_DATA_ROOT}/tunnel/` → `/home/ziggy/.zrok2` (enablement state). |