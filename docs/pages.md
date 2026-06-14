# Cove Pages

Cove Pages is a Forgejo-native static site hosting service. Push your site source to a `pages` branch on your Forgejo instance, and Forgejo Actions builds and deploys it automatically. Sites are served at `{owner}.pages.cove`.

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
  `https://{owner}.pages.cove/`
- **Named repo** (any other repo name):
  `https://{owner}.pages.cove/{repo}/`

## SSG Auto-Detection

The `configure-pages` action detects your static site generator automatically based on files present in the repository root.

| File | SSG | Build command |
|---------------------|----------|-------------------------|
| `hugo.toml` | Hugo | `hugo` |
| `_config.yml` | Jekyll | `bundle exec jekyll build` |
| `config.toml` | Zola | `zola build` |
| `next.config.*` | Next.js | `npm run build` |
| `package.json` | (fallback) | `npm run build` |

If no known SSG is detected, the action defaults to serving the repository root as static files.

## TLS

mkcert generates locally-trusted wildcard certificates for `*.pages.cove`. All pages subdomains have valid TLS with no browser warnings when the mkcert root CA is installed (which `cove up` does automatically).

### Custom Domains

Custom domains are not supported. Sites are only available at `{owner}.pages.cove` URLs.

## Troubleshooting

### Site not appearing after push

1. Check that the `pages` branch exists in your repository.
2. Verify Forgejo Actions ran successfully in the Actions tab.
3. Confirm the workflow file is at `.forgejo/workflows/pages.yml`.
4. Check that the `GITHUB_TOKEN` (Forgejo Actions token) is available in the workflow environment.

### 404 on a named repo

Ensure the repo name in the URL matches exactly (case-sensitive). The deploy action writes to `{owner}/{repo}`, so `https://alice.pages.cove/My-Docs/` will not match a repo named `my-docs`.

### Actions not triggering

Forgejo Actions must be enabled in the repository settings. Go to Settings → Actions → Enable actions, and ensure the `pages` branch is not excluded.