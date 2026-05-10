---
source-url: https://code.squarecows.com/SquareCows/pages-server
fetched: 2026-05-09
type: repository
title: SquareCows/pages-server — Traefik middleware for Forgejo/Gitea pages
---

## SquareCows/pages-server

A Traefik middleware plugin that provides GitHub Pages / GitLab Pages style static site hosting for Forgejo and Gitea. Written in Go with Python and shell components.

### How It Works

- Installable as a Traefik plugin (middleware)
- Watches Forgejo/Gitea repositories for changes
- Serves static files from the `public/` folder of repositories
- Supports `.pages` configuration file per repository

### Features

- **In-memory caching**: Files cached in memory (default TTL: 300 seconds)
- **Optional Redis caching**: For distributed deployments
- **Efficient serving**: Direct content serving without disk I/O
- **Traefik router integration**: Automatic router registration for custom domains and base pages domain via Redis provider
- **Auto-discovery**: No manual configuration — repos with a `public/` folder are served automatically
- **Disable/enable per site**: Set `enabled: false` in the repository's `.pages` file

### .pages Configuration

```yaml
enabled: true
custom_domain: example.com          # optional
enable_branches:                    # optional: branch subdomains
  - stage
  - qa
```

### Access Control

- **Public repos**: Accessible by default
- **Private repos**: Use `forgejoToken` for authenticated access
- **HTTP/HTTPS split**: Routers must be split between HTTP and HTTPS entrypoints; middleware handles ACME challenges on HTTP before redirecting to HTTPS

### Target

Requires a Traefik reverse proxy setup. Performance target: <5ms response time with caching.
