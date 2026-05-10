---
source-url: https://github.com/Ronmi/forgejo-pages
fetched: 2026-05-09
type: repository
title: Ronmi/forgejo-pages — Simple static page service for Forgejo/Gitea
---

## Ronmi/forgejo-pages

A simple, lightweight static page server for Forgejo and Gitea. Written in Go. Serves files from a `static-pages` branch of repositories via the Forgejo API.

### Modes

**Serve mode** — Starts an HTTP server. Requests are forwarded to the Forgejo API to fetch file content from the `static-pages` branch. Basic caching via ETag and Last-Modified headers.

```bash
forgejo-pages serve --token my-secret-token --server https://git.example.com --bind :8080 --branch static-pages
```

**Webhook mode** — Downloads content to disk via git clone/pull when webhooks fire. Requires a reverse proxy (nginx) to serve the files.

```bash
forgejo-pages listen --user myuser --token my-secret-token --server https://git.example.com --bind :8080 --branch static-pages --dir ./data
```

### Docker

```bash
# Serve mode
docker run -p 8080:8080 ronmi/forgejo-pages serve -s https://git.example.com -k my-secret-token

# Webhook mode
docker run -p 8080:8080 -v $(pwd)/data:/data ronmi/forgejo-pages:git listen -u myuser -k my-secret-token -s https://git.example.com -a :8080 -b static-pages -d /data
```

### Configuration

Flags can be set via environment variables (e.g., `PAGES_BIND`, `PAGES_BRANCH`) or a config file. API token permissions: repositories the token cannot read will return errors in serve mode or fail to download in webhook mode.

### Comparison

The project README itself recommends [Codeberg pages-server](https://codeberg.org/Codeberg/pages-server/) for an all-in-one solution. Ronmi/forgejo-pages is a simpler, lighter alternative.

### License

MPL-2.0
