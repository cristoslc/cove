---
source-url: https://codeberg.org/git-pages/git-pages
fetched: 2026-05-09
type: repository
title: git-pages — Scalable static site server for Git forges
---

## git-pages

**git-pages** is the premier GitHub Pages replacement for Forgejo and other Git forges. It powers Codeberg Pages and is developed by Catherine (whitequark) on Codeberg. Written in Go, it scales horizontally and works with filesystem or S3 storage backends.

### Quickstart

```bash
mkdir -p data
cp conf/config.example.toml config.toml
PAGES_INSECURE=1 go run .
```

Publish a site:
```bash
curl http://localhost:3000/ -X PUT --data https://codeberg.org/git-pages/git-pages.git
```

### Deployment

- **Standalone Docker**: `docker run -u $(id -u):$(id -g) --mount type=bind,src=$(pwd)/data,dst=/app/data -p 3000:3000 codeberg.org/git-pages/git-pages:latest`
- **With Caddy (TLS)**: Uses Caddy for automatic Let's Encrypt certificates. Exposes ports 80 and 443.
- **S3 backend support**: Can store site data and TLS key material in S3-compatible stores.

### Features

- Serves static files via GET/HEAD; selects site by hostname + project name
- Accepts PUT (repo URL or archive), POST (webhook), PATCH (partial update), DELETE
- Supports `_redirects` and `_headers` files (Netlify-compatible)
- Supports `Basic-Auth:` pseudo-header for password protection (low-stakes only)
- Atomic content updates
- Symlink-based deduplication via `/git/blobs/<git-sha256>`
- Prometheus metrics, syslog integration
- DNS-based authorization (TXT records, wildcard matching), forge authorization

### Architecture

v2 uses content-addressed blob storage in S3/filesystem. Manifests are Protobuf objects mapping paths to blob references. Updates atomically replace deployed manifest.

### Limitations

- No SHA-256 git hash support yet (limited by go-git)
- No Git LFS support (security concerns)
- Custom domains still migrating from legacy v2 codebase

### License

0-clause BSD

### Companion Tools

- [git-pages-cli](https://codeberg.org/git-pages/git-pages-cli) — CLI tool for publishing
- [Forgejo Action](https://codeberg.org/git-pages/action) — CI/CD integration
- [Grebedoc](https://grebedoc.dev) — Managed git-pages instance with CDN edge nodes worldwide
