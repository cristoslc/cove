---
source-url: https://forgejo.org/docs/next/user/actions/
fetched: 2026-05-09
type: web-page
title: DIY approach — Forgejo Actions + web server
---

## DIY Approach: Forgejo Actions + Any Web Server

The most manual but most flexible approach: use Forgejo Actions (CI/CD) to build and deploy static sites to any web server (Caddy, nginx, Apache, etc.).

### How It Works

1. **Write a Forgejo Actions workflow** that builds your static site (Hugo, Astro, Zola, Jekyll, plain HTML, etc.).
2. **Deploy output**: Copy the build artifacts to a web server directory. Options:
   - `rsync`/`scp` to a remote server
   - `docker cp` to a local container
   - Push to a deployment branch consumed by a webhook
   - Upload to S3/object storage served by a CDN
3. **Configure the web server** to serve the static directory.

### Example (Simplified Caddy)

```yaml
# .forgejo/workflows/deploy.yaml
on: [push]
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: hugo --minify
      - run: rsync -avz public/ user@server:/var/www/mysite/
```

### Pros and Cons

| Pros | Cons |
|------|------|
| Maximum flexibility | No automatic Pages-like URL scheme |
| Works with any web server | No per-repo auto-discovery |
| No extra dependencies | Must manage web server config yourself |
| Simple to understand | No `.pages` config file convention |

### Community Context

This pattern is commonly discussed in self-hosting forums as the "just use CI/CD + nginx" answer. It's not a Pages replacement per se — it puts you in full control of the deployment pipeline and web server.
