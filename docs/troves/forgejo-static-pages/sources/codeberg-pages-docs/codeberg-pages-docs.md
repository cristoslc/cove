---
source-url: https://docs.codeberg.org/codeberg-pages/
fetched: 2026-05-09
type: documentation-site
title: Codeberg Pages Documentation
---

## Codeberg Pages

Codeberg Pages is the hosted GitHub Pages equivalent for codeberg.org, powered by the **git-pages** engine. It serves as both a service and a reference implementation of how git-pages works with Forgejo.

### How It Works

Two deployment methods:

1. **Webhook method** (documented on main page):
   - Create a `pages` branch in your repo
   - Add a Forgejo-type webhook pointing to `https://USERNAME.codeberg.page/REPOSITORY`
   - Branch filter: `pages`
   - Push static content to the `pages` branch → auto-published

2. **Forgejo Actions method**:
   - Use Forgejo Actions CI/CD to build a static site (Hugo, Jekyll, etc.)
   - Deploy build output to Codeberg Pages using the git-pages Action
   - Separate documentation page at `/codeberg-pages/forgejo-actions/`

### URL Scheme

- User/org site: `https://USERNAME.codeberg.page/` (from `pages` repo)
- Repository site: `https://USERNAME.codeberg.page/REPOSITORY/` (from any repo's `pages` branch)
- Custom domains: via `.domains` file + DNS records (currently on legacy v2, migrating to git-pages)

### Migration Status

Codeberg Pages is actively migrating from its legacy v2 codebase to the git-pages engine. Custom domains still use the old method; `codeberg.page` subdomains already use git-pages. Breaking changes documented at `/codeberg-pages/migrating-from-pages-v2/`.

### Self-Hosting

git-pages can be self-hosted. It works with any Forgejo instance and many other Git forges. Documentation at [git-pages.org](https://git-pages.org/).
