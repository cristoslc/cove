---
source-url: https://forgejo.org/docs/next/contributor/static-pages/
fetched: 2026-05-09
type: web-page
title: Static pages | Forgejo Contributor Guide
---

## Official Forgejo Static Pages Documentation

Forgejo does **not** include a built-in GitHub Pages equivalent. The official documentation describes the infrastructure used by the Forgejo project itself — an LXC container dedicated to hosting static HTML pages, deployed manually or via webhook-triggered `git pull` scripts, with nginx as the frontend web server and certbot for TLS.

### Infrastructure Design

- **LXC container**: A dedicated LXC container runs nginx + a shell script.
- **nginx**: Serves static content from `/var/www/` directories. Each domain gets its own server block.
- **Webhook mechanism**: A POST webhook fires at `/.well-known/forgejo/<domain>` after a push. The URL returns 404 by design — the web server access logs are tailed by a shell script that extracts the domain name and runs `git pull`.
- **Automated updates**:

```bash
sudo tail -f /var/log/nginx/access.log | \
  sed --silent --regexp-extended --unbuffered -e 's|.*\.well-known/forgejo/([^ /]+) .*|\1|p' | \
  while read server; do
    cd "/var/www/$server" && git pull
  done
```

- **systemd service** keeps the script running persistently.

### Key Takeaway

This is the project's own infrastructure recipe, **not** a built-in feature of Forgejo. Users must assemble their own solution using external tools.
