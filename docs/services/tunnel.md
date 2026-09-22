# Tunnel (zrok2 managed relay) for Cove

`cove tunnel` publishes a `.cove` service to the **public web** through a zrok.io managed relay (zrok2, free tier). It is an **optional, profiled** sidecar (`profile: tunnel`) — the default stack has zero zrok references, and everything works offline without it.

The client is a single sidecar container (`openziti/zrok2`, pinned) running the zrok2 CLI. It is **outbound-only**: no published ports, no inbound exposure, no VPS, no port-forwarding. Shares are **closed by default** — a share exists only while `cove tunnel up` keeps it active.

## Onboarding journey (one-time)

1. **Sign up at [myzrok.io](https://myzrok.io/)** (no credit card required) and copy your **account token** from the console.
2. **Store the token** in 1Password under the shared `Zrok Account` item (ADR-017 conventions), keyed so it is reused across machines:
   ```shell
   cove creds set 'op://Private/Zrok Account/account_token'
   ```
   `cove tunnel` reads it via `cove creds vault-get`. You can also set `ZROK_ACCOUNT_TOKEN` in the compose `.env` or your shell — that value is honored directly. If no token is found anywhere, the command **fails loudly** with setup instructions (never an anonymous fallback).
3. **Run `cove tunnel up`** — the sidecar starts, and the first `up` runs `zrok2 enable <token>` idempotently (state persists in `${COVE_DATA_ROOT}/tunnel/`, mounted at `/home/ziggy/.zrok2`).

## Usage

```shell
# Ad-hoc public share of the ingress (default target: https://nginx, Host preserved)
cove tunnel up
# → https://<random>.shares.zrok.io

# Share a specific .cove service through ingress, with a stable reserved name
cove tunnel up --public myforge
# → https://myforge.shares.zrok.io  (name survives restarts)

# Share an arbitrary target (a .cove service name reachable on the compose network)
cove tunnel up https://git.cove.local

# Private share — no public URL at all; the other side pulls with a token
cove tunnel up --private
# → zrok2 access private <token>  (from a second environment)
```

`cove tunnel up` **blocks** while the share is active (Ctrl-C or `cove tunnel down` tears it down). `cove tunnel ls` lists active shares; `cove tunnel down [NAME]` releases a named share or stops the sidecar.

### Targets and tunnel-to-ingress

The default target is `https://nginx` — the same path a local visitor takes, with the `Host:` header preserved, so Forgejo/Vault/etc. see their own identity. The tunnel is a **pipe**: no URL rewriting, no `sub_filter`. The app's identity (`ROOT_URL` etc.) stays with the app.

### Reserved names (zrok2 v2 conventions)

zrok2 v2 renamed the v1 verbs: `zrok reserve`/`zrok share reserved` are gone. Instead:

- `zrok2 create name <name>` — reserve a stable name (lowercase alphanumeric, 4–32 chars; enforced by `cove tunnel --public`).
- `zrok2 share public <target> -n public:<name> --headless` — share under that name.
- Public URLs live under **`shares.zrok.io`** (plural — v1's `share.zrok.io` is gone).
- `zrok2 modify name -r <name>` promotes an ephemeral name in place ("this share earned a permanent name").

`--public` is IaC-rendered via `ZROK_SHARE_NAME` in the compose `.env` when the tunnel profile is active (bringup), so the name survives restarts.

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