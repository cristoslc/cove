# Staging Pipeline

Cove uses a parallel staging stack for branch verification. The staging stack
runs alongside prod on alternate ports/container names/data-root so there is no
conflict with the running production stack.

## Scripts

| Script | Purpose |
|--------|---------|
| `deploy.sh <branch>` | Build wheel, `cove init` + `cove up --no-sudo --no-provision` against parallel staging stack. Outputs staging URL on stdout. |
| `e2e.sh <staging-url>` | Run 15 verification checks against staging: containers, health, PII-free, version, idempotency, inverse assertions. |
| `teardown.sh <staging-url>` | Tear down staging containers, stop staging-only Colima VMs (never prod's), remove all staging artifacts. |

## Usage

```bash
# Deploy branch to staging (reads state from $HOME/.cache/cove-staging/state.env)
URL=$(scripts/staging/deploy.sh cove-stateless-config)
echo "Staging at $URL"

# Run e2e checks
scripts/staging/e2e.sh "$URL"

# Tear down when done
scripts/staging/teardown.sh "$URL"
```

## Staging stack details

- **Ports**: nginx 8444/8081, forgejo SSH 2223, dnsmasq 5354
- **Container names**: `cove-staging-*` (nginx, forgejo, vault, dnsmasq, dnsproxy)
- **Data root**: `~/Documents/cove-staging-data/`
- **Compose project**: `cove-staging`
- **HOME**: `$HOME/.cache/cove-staging/home.XXXXXX` (under real HOME so Colima's VirtioFS mount sees it)
- **No sudo**: pf/hosts/resolver tasks are `failed_when:false`; mkcert install skipped (CA already trusted)
- **Access**: `curl -H "Host: git.cove" https://127.0.0.1:8444/` (no DNS resolution, direct HTTPS)

## Limitations

- **Provisioning skipped** (`--no-provision`): vault unseal, forgejo admin creation, seed templating not exercised.
- **Colima UDP**: Colima doesn't forward UDP reliably; dnsmasq check uses `dig +tcp`.
- **Cert symlinks**: nginx config references `fullchain.pem`; staging pre-creates symlinks to `cove.local.pem` (mkcert's actual output).