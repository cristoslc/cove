# Cove Pages

Cove Pages is a Forgejo-native static site hosting service. Push your site
source to a `pages` branch on your Forgejo instance, and Forgejo Actions
builds and deploys it automatically. Sites are served at
`{owner}.pages.cove.{fqdn}`.

## Prerequisites

- A running Cove instance (Forgejo + Docker Compose + nginx + dnsmasq)
- A project repository on your Forgejo instance
- Forgejo Actions enabled for the repository

## Quick Start

Create a `.forgejo/workflows/pages.yml` file in your repository:

```yaml
on:
  push:
    branches: [pages]

jobs:
  pages:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: cove/configure-pages@main
      - uses: cove/build-pages@main
      - uses: cove/upload-pages-artifact@main
      - uses: cove/deploy-pages@main
```

Push to the `pages` branch and your site will be live at:

- **Owner root site** (if the repo is named `pages`):
  `https://{owner}.pages.cove.{fqdn}/`
- **Named repo** (any other repo name):
  `https://{owner}.pages.cove.{fqdn}/{repo}/`

## SSG Auto-Detection

The `configure-pages` action detects your static site generator
automatically based on files present in the repository root.

| File                | SSG      | Build command           |
|---------------------|----------|-------------------------|
| `hugo.toml`         | Hugo     | `hugo`                  |
| `_config.yml`       | Jekyll   | `bundle exec jekyll build` |
| `config.toml`       | Zola     | `zola build`            |
| `next.config.*`     | Next.js  | `npm run build`         |
| `package.json`      | (fallback) | `npm run build`       |

If no known SSG is detected, the action defaults to serving the
repository root as static files.

## Limitations

### TLS

Tailscale certificates do not support wildcard domains. The
`*.pages.cove.{fqdn}` subdomain pattern has no valid TLS certificate
today. Browsers will display a certificate warning when accessing pages
subdomains over HTTPS.

Options to close this gap:
1. Use a wildcard certificate from an ACME provider with DNS-01 challenge.
2. Issue per-owner certificates via Tailscale with SNI-based selection.
3. Serve pages over HTTP only, relying on the Tailscale mesh for
   in-transit encryption.

### Custom Domains

Custom domains are not supported. Sites are only available at
`{owner}.pages.cove.{fqdn}` URLs.

## Troubleshooting

### Site not appearing after push

1. Check that the `pages` branch exists in your repository.
2. Verify Forgejo Actions ran successfully in the Actions tab.
3. Confirm the workflow file is at `.forgejo/workflows/pages.yml`.
4. Check that the `GITHUB_TOKEN` (Forgejo Actions token) is available
   in the workflow environment.

### 404 on a named repo

Ensure the repo name in the URL matches exactly (case-sensitive). The
deploy action writes to `{owner}/{repo}`, so
`https://alice.pages.cove.fqdn/My-Docs/` will not match a repo named
`my-docs`.

### Certificate warning on HTTPS

This is expected. See the TLS limitation above. Access the site over
HTTP or accept the browser warning to proceed.

### Actions not triggering

Forgejo Actions must be enabled in the repository settings. Go to
Settings → Actions → Enable actions, and ensure the `pages` branch is
not excluded.