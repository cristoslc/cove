---
type: web-page
name: chameth.com — Migrating from GitHub to Forgejo
url: https://chameth.com/migrating-from-github-to-forgejo/
fetched: 2026-06-04
author: Chris Smith
published: 2026-04-30
---

# Migrating from GitHub to Forgejo — Chris Smith's Practical Experience

A detailed blog post about a real-world Forgejo migration covering mirroring and PR handling.

## Mirroring Setup

- Forgejo's built-in push mirror pushes code changes to GitHub automatically
- Also mirrors to Codeberg as a secondary public presence
- Code sync works well with push mirror

## Custom PR Import Tool

Chris built a **small private tool** to handle GitHub pull requests:

1. Takes a GitHub PR URL as input
2. Creates a fork in a `prs` organization on Forgejo (if not exists)
3. Pushes PR contents to a branch in the fork
4. Creates a PR from the `prs` repo into the main repo
5. CI runs on the imported PR
6. After approval, merge in Forgejo UI
7. Push mirror syncs merge to GitHub
8. **GitHub automatically marks the PR as merged**

## Key Workflow

- Primary development on Forgejo
- Push mirror to GitHub for public visibility
- External contributors submit PRs on GitHub
- Custom import tool brings PRs into Forgejo for review and CI
- Merges happen in Forgejo, mirror pushes back to GitHub

## Security Approach

- Forgejo not exposed to internet (runs on Tailscale private network)
- Import tool runs as a user with limited permissions (can write to `prs` org, only submit PRs to public repos)
- CI approval required for imported PRs before running workflows

## Limitations Noted

- Without the custom tool, merging a GitHub PR directly would be overwritten by push mirror
- The custom tool is private, not published as open source
- Low volume of external PRs makes the semi-manual workflow acceptable