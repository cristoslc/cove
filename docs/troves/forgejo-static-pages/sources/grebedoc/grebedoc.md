---
source-url: https://grebedoc.dev
fetched: 2026-05-09
type: web-page
title: Grebedoc — Managed static site hosting for Git forges
---

## Grebedoc

Grebedoc is a **managed instance of git-pages** configured as a CDN with edge nodes worldwide. It provides hosted GitHub Pages-style functionality for any Git forge.

### What It Is

- Not a separate project — it's git-pages + a global CDN deployment
- Push-based architecture: Git forges notify the server via webhooks when content updates
- Supports Forgejo, Gitea, Gogs, and GitHub

### Value Proposition

If you want something like GitHub Pages but not from Microsoft, and you don't want to self-host the pages server yourself, Grebedoc provides the hosting layer. You still need your own Git forge.

### Comparison

| Aspect | Codeberg Pages | Grebedoc |
|--------|---------------|----------|
| Hosting | Free on codeberg.org | Managed CDN |
| Git forge | Codeberg (hosted) | Any forge |
| Self-hostable | Yes (git-pages) | Yes (git-pages + Nix) |
| Custom domains | Yes | Yes |

Source: whitequark's Reddit post on r/selfhosted.
