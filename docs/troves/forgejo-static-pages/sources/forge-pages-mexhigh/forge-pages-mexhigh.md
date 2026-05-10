---
source-url: https://github.com/MexHigh/Forge-Pages
fetched: 2026-05-09
type: repository
title: MexHigh/Forge-Pages — CI/CD-driven static page server with OAuth2
---

## MexHigh/Forge-Pages (Forge Pages)

A CI/CD-driven static page server for Forgejo and Gitea that integrates OAuth2 for permission enforcement. Written in Go. Designed for private pages as well as public ones.

### Key Features

- **CI/CD-driven**: Unlike other solutions that require committed static assets in a branch, Forge Pages lets you build and deploy from within a workflow.
- **OAuth2 integration**: Protects pages using the Forgejo/Gitea OAuth2 provider. Enforces repository permissions — a user must log in and have access to the originating repository to view protected pages.
- **GitHub Pages URL layout**: `https://<owner>.<base-url>/<repo>/*`
- **Optional base path**: Additional path after `<repo>` for separate protection (useful for multiple versions or PR previews).
- **Forgejo Action available**: The action repository is public and works from GitHub Actions or other Forgejo/Gitea instances.

### Deployment Endpoint

The server exposes a `POST /deploy` endpoint. Deploy from CI:

```json
{
  "repo": "user/repo",
  "branch": "pages",
  "files": "<archive>"
}
```

### Configuration

- `forge_url` — URL to your Forgejo/Gitea instance
- `protect` flag — enables OAuth2 protection for the page
- `-skip_deploy_checks` — skips access token validation (useful when you don't need auth)

### Use Case

Best fit for teams needing private documentation or internal static sites with access control tied to repository permissions. Also suitable for public deployments via Forgejo Actions.

### Project Page

[leon-schmidt.dev/en/projects/forge-pages/](https://leon-schmidt.dev/en/projects/forge-pages/) — project author's description and motivation.
