# git-bug — Trove Synthesis

## Key Findings

git-bug is a distributed, offline-first bug tracker embedded in git. It stores issues as git objects (not files) under `refs/bugs/` and syncs via regular `git push`/`git pull`. It has CLI, TUI, and web UI interfaces. It bridges to GitHub and GitLab for issues (but not PRs). A Forgejo/Gitea bridge is in progress as a draft PR.

### Data Model

Issues (called "bugs" internally) are stored as chains of git commits under `refs/bugs/<id>`. Each commit contains an `OperationPack` — a JSON blob referencing git blobs. Operations are:

| Type | Description |
|------|-------------|
| CreateOp | Initial creation (title + message + files) |
| SetTitleOp | Change title |
| AddCommentOp | Add a comment |
| SetStatusOp | Open/close |
| LabelChangeOp | Add/remove labels |
| EditCommentOp | Edit existing comment |
| NoOpOp | Placeholder |
| SetMetadataOp | Attach arbitrary key/value metadata |

This is an **event-sourcing model** — the current state of a bug is derived by replaying all operations in order. This is conflict-free by design: concurrent edits create branches in the DAG, and git-bug creates merge commits to reconcile them. Ordering uses Lamport clocks (`refs/bugs-create` and `refs/bugs-edit`).

### What git-bug Supports

| Feature | Core | CLI | TUI | WebUI |
|---------|:----:|:---:|:---:|:-----:|
| Issues | ✅ | ✅ | ✅ | ✅ |
| Comments | ✅ | ✅ | ✅ | ✅ |
| Labels | ✅ | ✅ | ✅ | ✅ |
| Title edits | ✅ | ✅ | ✅ | ✅ |
| Status (open/close) | ✅ | ✅ | ✅ | ✅ |
| Comment editing | ✅ | ✅ | ❌ | ✅ |
| Metadata | ✅ | ✅ | — | — |
| Milestones | ❌ | ❌ | ❌ | ❌ |
| Assignees | ❌ | ❌ | ❌ | ❌ |
| **Pull requests** | **❌** | **❌** | **❌** | **❌** |
| Attachments/media | 🟠 | ❌ | ❌ | ❌ |

### ID System

IDs are SHA-256 hashes (64 hex chars) of the serialized operation data. Content-addressed, stable across clones. Human-readable IDs are the first 7 characters. Unambiguous prefix matching is supported.

### Threading

**No threading.** Comments are a flat list. There is no parent/child relationship. Each comment has a `CombinedId(bugId, operationId)` for stable reference, but no reply-to mechanism.

### Sync

Regular `git push`/`git pull` on `refs/bugs/*` and `refs/identities/*`. No special handling needed — Forgejo's git backend serves these refs natively. Lamport clocks ensure deterministic ordering after concurrent edits.

### Bridges

| Bridge | Import | Export | PRs |
|--------|--------|--------|-----|
| GitHub | ✅ | ✅ | ❌ |
| GitLab | ✅ | ✅ | ❌ |
| Jira | ✅ | ✅ | ❌ |
| Launchpad | ✅ | ❌ | ❌ |
| **Forgejo/Gitea** | **🟠 (draft PR #1565)** | ❌ | ❌ |

Bridges use `SetMetadataOp` to track the mapping between local and remote entities (e.g., `github-url=https://github.com/owner/repo/issues/123`).

### Web UI

React + TypeScript + GraphQL, embedded in the Go binary. Alpha quality. Supports issue CRUD (create, comment, label, close/reopen). No PR support, no milestones, no assignees. Authentication is local-only (no OAuth).

### Forgejo Bridge

PR #1565 (jyn514) is a WIP draft that implements import-only bridge for Forgejo/Gitea. It uses the Gitea SDK (Forgejo-compatible). Not yet merged. No export, no PR sync.

### License

GPLv3+

## Points of Agreement

- All bridges confirm: git-bug is issues-only. PRs are out of scope.
- The data model is well-designed for distributed sync (event sourcing + Lamport clocks + git refs).
- The Forgejo bridge work (PR #1565) confirms the Gitea SDK works with Forgejo instances.

## Points of Disagreement

- No disagreement found — git-bug's documentation is clear about what it does and doesn't support.

## Gaps

- No PR entity type, no PR data model, no PR workflow
- No threading model for comments
- No milestone or assignee support
- No Forgejo bridge (only a draft import-only PR)
- Web UI is alpha-quality, not production-ready
- No media/attachment support in any UI layer
- Authentication in the web UI is local-only (no OAuth for public-facing use)

## Sources

- `github.com/git-bug/git-bug` — main repository, 9.9k stars, v0.10.1
- `docs/` directory — architecture, data model, web UI docs
- `entities/bug/` — data model source code
- `bridge/` — bridge implementations
- PR #1565 — Forgejo/Gitea bridge (draft, import-only)
- Issue #80 — original Gitea integration request