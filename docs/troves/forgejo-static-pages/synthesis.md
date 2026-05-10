---
trove: forgejo-static-pages
generated: 2026-05-09
---

# Synthesis: Forgejo Static Pages

## The Core Answer

Forgejo does **not** have a built-in GitHub Pages equivalent. There is no native feature, plugin, or extension shipped with Forgejo that serves static websites from repositories. The official Forgejo docs describe the project's own infrastructure (LXC + nginx + webhook script), not a product feature.

However, the community has built several robust solutions, all of which are external services that integrate with Forgejo via API or webhooks.

## Recommended Solution: git-pages

**git-pages** is the clear front-runner. It was purpose-built as a GitHub Pages replacement for Forgejo, powers Codeberg Pages in production, and is actively maintained (commits as of May 2026). It is:
- Written in Go (single binary or Docker container)
- Horizontally scalable with filesystem or S3 backends
- Netlify-compatible (_redirects, _headers, Basic-Auth)
- Equipped with companion CLI and Forgejo Action
- 0-clause BSD licensed

For managed hosting without self-hosting the server, **Grebedoc** provides git-pages as a global CDN service.

## Other Community Solutions

| Project | Approach | Distinguishing Feature |
|---------|----------|------------------------|
| Ronmi/forgejo-pages | API proxy or webhook + git pull | Simplest, lightweight |
| MexHigh/Forge-Pages | CI/CD-driven + OAuth2 | Best for private pages with access control |
| SquareCows/pages-server | Traefik middleware plugin | Best for Traefik-based infrastructure |
| forgejo-pages-diy | Git hook on Forgejo server | Simplest, no external service |
| DIY (Actions + nginx) | CI/CD build → deploy to web server | Maximum flexibility |

## Points of Convergence

Every solution agrees that the pattern is: push static content to a branch (traditionally called `pages`) → notify a server → server serves the files. No solution modifies Forgejo itself. All are external.

## Points of Divergence

- **Caching and performance**: git-pages and SquareCows/pages-server emphasize caching and low latency. Ronmi/forgejo-pages in serve mode relies on API forwarding to the forge. DIY approaches push caching responsibility to the web server layer.
- **Access control**: Only MexHigh/Forge-Pages integrates OAuth2 for permission enforcement tied to repository access. Others either serve only public repos or rely on reverse proxy auth.
- **Deployment model**: CI/CD-driven (Forge-Pages) vs. webhook-triggered git pull (git-pages, Ronmi) vs. hook-based (forgejo-pages-diy) vs. middleware auto-discovery (SquareCows).

## Gaps

- **No first-party roadmap**: Forgejo has not announced plans to build a native Pages feature. Any such feature would require significant architectural changes.
- **No Forgejo-runner-native deployment**: All solutions currently require an external HTTP server (except forgejo-pages-diy which piggybacks on the forge server itself). None leverage Forgejo Actions as the serving layer directly — they use Actions only for building.
- **No federation integration**: Static pages do not interact with ForgeFed/ActivityPub federation, which is Forgejo's primary roadmap focus.
