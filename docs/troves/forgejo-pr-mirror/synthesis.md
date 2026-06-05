# Forgejo ↔ GitHub PR Mirroring — Trove Synthesis

## Key Findings

There is **no complete, production-ready, open-source solution for mirroring pull requests** between Forgejo and GitHub. Every approach has significant limitations.

### What Exists

**1. Code-only mirroring (built into Forgejo):** Forgejo's built-in push/pull mirrors handle branches, tags, and commits. No issues, PRs, labels, or other metadata are synced. This is the simplest and most reliable option for code sync.

**2. Forgesync — Forgejo → GitHub metadata sync:** Syncs repository metadata including PR state from Forgejo to GitHub. One-way only. Works well if Forgejo is primary and GitHub is a read-only mirror. PRs are synced as metadata, not full conversation threads.

**3. Gitea Mirror — GitHub → Forgejo sync with web UI:** Syncs from GitHub to Forgejo but PRs become enriched issues, not native PR objects. This is a fundamental API limitation of Gitea/Forgejo — there is no API to create pull requests from external sources as actual PR objects.

**4. Custom webhook/import tool (chameth.com approach):** A private tool that imports GitHub PRs into Forgejo as real PRs by creating forks and branches. Works but is unpublished and requires maintenance.

### Fundamental Limitations

- **Forgejo's API cannot create PRs from external sources** as native PR objects with full diff/merge functionality. This is the root limitation.
- **Forgejo team has closed related feature requests** (issue #5367 for issue sync on mirrors, #7556 for full two-way has no activity).
- **No bidirectional PR sync exists.** True two-way PR sync is not practically achievable today.
- **Push mirror force-pushes** to remote, which means merging a GitHub PR directly would be overwritten on the next sync.

### Recommended Approaches by Use Case

| Use Case | Best Approach |
|----------|--------------|
| **Primary on Forgejo, read-only GitHub mirror** | Forgejo push mirror (code) + Forgesync (PR/issue metadata) |
| **Primary on GitHub, backup to Forgejo** | Push from GitHub or use Gitea Mirror (PRs as issues) |
| **Hybrid — dev on Forgejo, public on GitHub with contributor PRs** | Push mirror + custom webhook tool to import GitHub PRs into Forgejo |
| **Full bidirectional (unsolved)** | Does not exist. Watch Forgejo issue #7556. |

The most practical architecture for the cove project (Forgejo primary, GitHub secondary) is push mirror for code + Forgesync for PR/issue metadata, accepting that GitHub is a read-only mirror for public visibility. If bidirectional contributor PRs are needed, a custom import tool similar to chameth.com's approach would need to be built.

## Points of Agreement

- All sources agree Forgejo's built-in mirroring is code-only
- All sources agree there's no full bidirectional PR mirroring solution
- All sources confirm the Gitea/Forgejo API cannot create real PRs programmatically from external sources

## Points of Disagreement

- Forgesync treats PRs as metadata that can be reflected; Gitea Mirror treats them as enriched issues. Different philosophies for the same fundamental limitation.
- Whether the "PRs as enriched issues" approach is useful or confusing depends on the workflow and contributor expectations.

## Gaps

- No source covers a fully automated webhook-based bridge that maintains PR identity (comments, reviews, status checks) bidirectionally
- No tested solution exists using Forgejo Actions as the sync orchestrator
- No performance/scale data for large repositories with many PRs