---
type: repository
name: Gitea Mirror
url: https://github.com/RayLabsHQ/gitea-mirror
fetched: 2026-06-04
language: TypeScript (Bun, Astro, React)
license: AGPL-3.0
---

# Gitea Mirror

Automatically mirrors repositories from GitHub to self-hosted Gitea/Forgejo. Web UI with Docker deployment.

## Key Features

- Mirror public, private, and starred GitHub repos to Gitea/Forgejo
- GitHub Enterprise Server (GHES) and GHEC with data residency support
- Mirror entire organizations with flexible strategies
- Git LFS support
- **Metadata mirroring**: Issues, Pull Requests, Labels, Milestones, Wiki, Releases
- Real-time dashboard with activity logs
- Scheduled automatic mirroring with configurable intervals
- Auto-discovery of new GitHub repositories
- Repository cleanup (remove repos deleted from GitHub)
- Force-push protection (Beta)

## PR Mirroring Implementation

**Pull requests cannot be created as actual PRs in Gitea/Forgejo** due to API limitations. Instead, they are mirrored as **enriched issues** with:

- Special "pull-request" label for identification
- `[PR #number]` prefix in title with status indicators (`[MERGED]`, `[CLOSED]`)
- Original author and creation date
- Complete commit history (up to 10 commits with links)
- File changes summary with additions/deletions
- List of modified files (up to 20 files)
- Original PR description and comments
- Base and head branch information
- Merge status tracking

PRs appear in the issue tracker with clear visual distinction.

## Direction

GitHub → Gitea/Forgejo only (one-way mirror).

## Deployment

```yaml
docker compose -f docker-compose.alt.yml up -d
```

Configuration via web UI or environment variables. Nix/NixOS support also available.

## Limitations

- PRs lose native PR semantics (no merge button, no diff view)
- One-way only (GitHub → Forgejo)
- Requires careful interval configuration to match Gitea/Forgejo's MIN_INTERVAL
- Token rotation requires manual update of stored mirror credentials