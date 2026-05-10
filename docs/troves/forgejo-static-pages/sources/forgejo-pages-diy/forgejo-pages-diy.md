---
source-url: https://codeberg.org/coderofsalvation/forgejo-pages-diy
fetched: 2026-05-09
type: repository
title: coderofsalvation/forgejo-pages-diy — git hook approach
---

## coderofsalvation/forgejo-pages-diy

A minimalist "do it yourself" approach using Forgejo's git hooks. No external service needed — it piggybacks on Forgejo's own server to serve static content.

### Approach

- Uses a **git hook** (post-receive) installed directly on the Forgejo server
- When a push lands on the `pages` branch, the hook copies or builds static content to a directory that Forgejo can serve
- Simplest method: just install the githook script

### Trade-offs

- **Simplest setup** of all options — no external service, no reverse proxy configuration
- **Tight coupling** to the Forgejo server — requires filesystem access to the server
- **No isolation** — static site lives on the same machine as your forge
- **Manual setup** — requires hook installation per repository or a global hook
- Not suitable for containerized/Docker Forgejo deployments without volume mounts

### Best For

Quick-and-dirty personal projects, small single-user Forgejo instances where simplicity trumps scalability.

Mentioned in Reddit discussions as the "simplest way" to get GitHub Pages-like behavior on Forgejo.
