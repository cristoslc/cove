---
title: "Multi-Stage .cove — Operator-Centric with Always-Online Tier-2"
created: 2026-06-13
authored-by: deepseek-v4-flash:cloud, glm-5.1:cloud
status: Draft
---

# Multi-Stage .cove

## Hard Constraints

These are non-negotiable, set by the project worldview:

1. **PR/Issue sync is the whole point.** Without it, multi-stage is just "git push to a remote," which is trivial and solved. The hard part — keeping PRs, issues, and their comments in sync across instances — is the actual feature.
2. **Offline-first is immutable.** Local Coves must work fully without the always-online tier. Disconnected operation is the normal mode, not degraded mode.
3. **No public forge dependency.** No Codeberg, no GitHub, no shared external service. The operator owns all instances end-to-end.

## Use Cases (Operator-Centric, No External Collaborators)

Multi-stage Cove is not about collaboration with other people. It's about the operator's own operational needs:

### 1. Phone Access

The operator wants to read and comment on issues and PRs from their phone. The phone is a **read-and-comment client**, not a development surface. It uses Forgejo's web UI (mobile-friendly) or a mobile browser pointed at the always-online tier-2. The phone does not run a local Cove, does not run a sync daemon, does not store state — it just makes HTTPS requests to tier-2.

### 2. Always-Online Tier-2 (Laptop Independence)

Laptops are not always online — they sleep, the lid closes, they go in a bag. Tier-2 cove is a **standby copy that's always reachable**. It can run on:
- A Raspberry Pi at home
- An old laptop repurposed as a home server
- A low-cost VPS (if the operator accepts the cloud dependency for tier-2 only)
- A desktop that's always on

The operator can check their PRs from their phone, tablet, or any device — even when all their laptops are asleep. Tier-2 is the single point of presence when the operator is "away from their desk."

### 3. Multiple Local Nodes, One Project

The operator has multiple machines (MacBook, Linux desktop, home server, etc.) that may all work on the same project with different branches. Each machine runs its own local Cove. All local Coves sync to the same tier-2.

```
┌─ local cove (MacBook) ─────────┐
│  forgejo: branches, PRs        │──┐
│  runner: local CI              │  │
└────────────────────────────────┘  │
                                    │  sync (push/pull)
┌─ local cove (Linux box) ────────┐  │
│  forgejo: branches, PRs        │──┤
│  runner: local CI              │  │
└────────────────────────────────┘  │
                                    ▼
                    ┌─ tier-2 cove (always online) ─┐
                    │  forgejo: aggregated state    │
                    │  Pages: public preview        │
                    │  Notifications: enabled       │
                    └───────────────────────────────┘
                                    ▲
                                    │ HTTPS (read+comment)
                    ┌────────────────────────────────┐
                    │  Phone (browser or app)        │
                    │  No local state, no sync       │
                    └────────────────────────────────┘
```

#### PR-Sashaying: Nodes + Branches

PR-sashaying means each machine makes branches. Git is good at branches. With a handful of machines (not thousands of users), collision is trivially avoided by prefixing branch names with a per-node identifier rather than requiring a global registry.

```
macbook/feature-x       # MacBook's work on feature-x
linux/feature-x         # Linux box's work on feature-x (same feature, different branch)
server/docs-update      # Server's work on documentation
```

Each node creates PRs from its own prefixed branches. Tier-2 receives all branches from all nodes. No collision at the git level — different branch names, different git refs. No collision at the PR level — different source branches, different PRs (one per node per feature).

#### The Rebase Step

When MacBook and Linux both work on `feature-x`, they may diverge. The operator's normal git workflow handles this: `git fetch`, `git rebase`, resolve conflicts. What does the sync layer need to do?

**Nothing.** The sync layer pushes branches and PRs. It does not rebase. The operator rebases on whichever machine they sit down at. The sync layer just mirrors the state after the operator resolves:

1. MacBook pushes `macbook/feature-x` to tier-2
2. Linux pushes `linux/feature-x` to tier-2
3. Tier-2 has both branches (and potentially two PRs for the same feature)
4. Operator sits down at MacBook, `git fetch tier2`, sees both branches
5. Operator rebases `macbook/feature-x` onto `main`, merges `linux/feature-x` work if desired
6. MacBook pushes rebased branch; sync layer mirrors to tier-2
7. Operator closes the PRs or merges them

The sync layer doesn't touch branches. It mirrors git refs. Git already solves the distributed branching problem — the sync layer just ensures all refs are visible everywhere.

#### No CI on Tier-2 (V1 Scope)

Tier-2 has no runner and no Vault in v1. CI runs locally on each node. The phone sees PR status only when it was computed on a local runner and synced as part of the event log. If a PR has CI status from MacBook's runner, that status syncs to tier-2 so the phone sees "CI passed." If no local runner has run CI for a given PR, the phone sees "no status."

Vault stays local too — each local node has its own Vault for secrets. Tier-2 doesn't need Vault for PR/issue sync. This keeps the scope tight: v1 is about PRs, issues, and comments on Forgejo instances. Vault and CI can be added later.

## Identity Model (Single-Operator)

The operator has one account (`cristos`) on every surface. That's it.

| Surface | Account | Scope |
|---------|---------|-------|
| Local Cove (MacBook) | `cristos` | Operator |
| Local Cove (Linux box) | `cristos` | Operator |
| Tier-2 Cove | `cristos` | Operator |
| Phone (web client on tier-2) | `cristos` | Operator (session) |

The operator logs in as `cristos` on whichever surface they're using. The same string is the author of every event everywhere. No mapping, no translation, no collision, no ghost users.

**Why this works:**
- The Forgejo foreign key constraint (every comment needs a real `poster_id`) is trivially satisfied: there's exactly one author, who is a real account on every instance.
- No `[bot]` convention, no machine-scoped accounts, no origin-instance tagging.
- No trust boundary — everything is "us."

**Lost: machine provenance.** We can't tell from an event whether it was authored on the MacBook or the Linux box. That information lives in the operator's local knowledge (which machine they were sitting at), not in the event log. If provenance matters, the operator adds it to the comment body ("tested on M2 MacBook Pro").

## Sync Architecture: Event Log via Git

PRs and issues are stored in Forgejo's database (SQLite for local Cove). To sync them between instances without modifying Forgejo, we extract state as an **append-only event log** and use a git repo as the log's storage. Git is offline-first by design, handles distributed sync via push/pull, and is already part of the Cove toolchain.

### Data Model

For each repository, a sync repo contains:

```
sync.git/
├── issues/
│   ├── 2026-06-13T09-42Z-macbook-crash-on-large-repos/
│   │   ├── comments/
│   │   │   ├── 042-macbook-cristos-2026-06-13T10-15Z.json
│   │   │   ├── 017-linux-cristos-2026-06-13T10-20Z.json
│   │   │   └── ...
│   │   └── logs/
│   │       ├── macbook-events.log    # append-only, owned by MacBook node
│   │       ├── linux-events.log      # append-only, owned by Linux node
│   │       └── tier2-events.log      # append-only, owned by tier-2 node
│   └── 2026-06-13T11-00Z-linux-slow-ci-on-arm/
│       └── ...
├── pulls/
│   ├── 2026-06-12T14-30Z-macbook-refactor-vault/
│   │   ├── comments/
│   │   ├── reviews/
│   │   └── logs/
│   │       ├── macbook-events.log
│   │       └── tier2-events.log
│   └── ...
├── mapping.json          # sync-dir-name → per-instance numeric IDs
└── refs/
    ├── heads/sync
    └── remotes/tier2/main
```

Each issue and PR has:
- A globally unique directory name — `{creation-timestamp}-{node}-{slug}`. No two nodes can create the same issue at the same timestamp with the same slug on the same project.
- Immutable comment files in `comments/` — each is a file, never edited, only added
- Per-node `logs/` — each node owns its own `{node}-events.log`, append-only, committed only by that node
- `mapping.json` at the repo root — maps each sync-dir-name to per-instance numeric issue/PR IDs

**No `meta.json` is committed.** The current state of an issue or PR is a derived cache computed by replaying all per-node event logs sorted by timestamp. Storing `meta.json` in git would create real merge conflicts — two nodes editing the same issue produce two different `meta.json` files. By keeping it derived, git only contains immutable additions (comment files) and append-only logs (events). Both are conflict-free under merge.

### Why Files Instead of Notes

Git notes tie metadata to commits. Issues and PRs aren't tied to commits — they're tied to branches (PRs) or independent of commits (issues). Files in a git tree are a more natural fit. Each comment is an immutable file; each state change is an event in a log. Append-only by construction.

### Sync Topology (Hub-and-Spoke)

Tier-2 is the hub. Every local Cove syncs bidirectionally with tier-2. Local-to-local sync does not happen directly.

```
local A ──┐
          ├──→ tier-2 ◀── phone (read-only via HTTPS)
local B ──┘
```

**Local → Tier-2 (push):**
1. Operator opens a PR on MacBook local
2. MacBook sync daemon detects the new event (via Forgejo webhook or DB poll)
3. Daemon writes a new comment file and appends to the event log
4. Daemon commits to the local sync repo
5. Daemon pushes to tier-2's sync repo (via SSH or HTTPS)
6. Tier-2 sync daemon pulls, reads new events, applies them to its Forgejo database

**Tier-2 → Local (pull):**
1. Operator comments on a PR from their phone via tier-2
2. Tier-2 sync daemon detects the comment
3. Daemon writes the comment file and appends to its event log
4. MacBook local sync daemon pulls from tier-2 (periodically, or on demand)
5. Daemon applies new events to its Forgejo database

**Linux box syncs the same way:** push to tier-2 when it has new events, pull from tier-2 when it comes online (laptop wakes, lid opens, etc.).

**Phone does not sync.** It's a thin HTTPS client on tier-2. No local state, no sync daemon, no event log. The phone's browser/app talks directly to tier-2's Forgejo web UI.

### Race Conditions and Resolution

**R1: Meta.json merge conflict.** Solved by removing `meta.json` from git entirely. The current state of an issue is a derived cache computed by replaying all per-node event logs sorted by timestamp. Only immutable additions (comment files) and append-only data (per-node event logs) live in git. Both are conflict-free under merge — a rebase just adds the other node's files and appends to the rebased node's log.

**R2: Git push contention.** Two nodes push to tier-2 simultaneously. One gets non-fast-forward. The sync daemon pulls with rebase (which is always clean — only additions, no edits), then retries push. Three-way retry loop; contention is rare with a handful of machines.

**R3: Comment ordering drift.** Nodes have independent clocks. If MacBook's clock is 5 minutes ahead, its comments sort after Linux's in replay order even though they were written first in wall-clock time. Mitigation: NTP on all Cove nodes. For a single operator, sub-second drift is the norm; second-level drift is visible but the operator can mentally reorder what they themselves wrote. If this becomes a problem in practice, tier-2 can assign a monotonic `received_at` timestamp on processing each event, which provides a global total order at the cost of complexity.

**R4: Two nodes independently replying to the same comment.** Forgejo's comment model is flat — no threading, no `in_reply_to`, no parent/child hierarchy. A "reply" is just a new comment. If both nodes post a comment referencing the same prior comment, they appear in `created_at` timestamp order. There is no notion of "indenting under the parent" because Forgejo doesn't do threads.

**R5: Comment branching — the big one.** Forgejo has no threading, so every comment is top-level in chronological order. The real problem: two nodes writing comments offline that, when merged, interleave in misleading ways:

```
MacBook offline:
  10:00 "I think this is a race condition."
  10:02 "A deadlock is a kind of race condition."  (still offline, hasn't seen Linux's comment)

Linux offline:
  10:01 "No, it's a deadlock."
```

When merged on tier-2 and sorted by `created_at`:
```
1. macbook: "I think this is a race condition."        (10:00)
2. linux:   "No, it's a deadlock."                      (10:01)
3. macbook: "A deadlock is a kind of race condition."   (10:02)
```

Comment 3 appears to respond to comment 2, but MacBook hadn't seen comment 2 when writing it. The converged order implies a causal chain that doesn't exist.

**For a single operator, this is acceptable.** The operator wrote all three comments. They know what they were thinking. NTP keeps clocks close enough that the order approximates wall-clock intent. The operator can mentally separate "follow-up to my earlier thought" from "reply to something the other machine wrote."

There is no threading fix because Forgejo doesn't support it. The only mitigation is that the tier-2 `received_at` timestamp could provide a causal order (when did tier-2 first learn of each comment?), but this is a different order than author intent and arguably more useful — it reflects the order in which the operator actually discovered information.

**R6: Two nodes create the same issue slug simultaneously.** Unlikely (human-written slugs), but possible. Mitigation: the sync-dir-name includes `{creation-timestamp}-{node}-{slug}`. If two nodes create `my-bug-report` at the exact same second, the timestamps and node IDs differ. The sync-dir-names are unique. The operator sees two issues with similar slugs and can close or link them. This is a UX concern, not a data integrity problem.

**R7: Tier-2 applies events slower than locals push.** A local pushes, then immediately pulls expecting to see its own events. Tier-2 hasn't finished applying them yet — the pull returns stale state. Mitigation: locals push and apply their own events to their local Forgejo before pushing. The pull-after-push is for OTHER nodes' events, not self-verification. If the local wants to verify its events are on tier-2, it checks the sync repo's HEAD (its commit is there) rather than Forgejo's API.

**R8: Per-node event log corruption.** An event log line is truncated due to a crash during write. Replay on tier-2 skips the corrupted line and logs a warning. The node's next push contains a repaired copy (or the node detects the corruption on its own next startup via CRC/length check and rewrites).

### Conflict Resolution Summary

| Conflict | Resolution |
|----------|-----------|
| Same comment file from two nodes | Impossible — filenames include `{seq}-{node}` prefix |
| Same event ID from two nodes | Impossible — IDs include `{node}` prefix |
| Same issue slug from two nodes | Different sync-dir-names due to `{timestamp}-{node}` prefix |
| Same issue edited by two nodes | Replay by timestamp — last write wins per field |
| Comment ordering across nodes | Sort by `created_at` timestamp; NTP for clock sync |
| Tier-2 push contention | Pull --rebase + retry (always clean due to additive-only git) |
| Flat comments (no threading in Forgejo) | No reply-to hierarchy; all comments are chronological |
| Comment branching (fake causal chains) | Tolerated for single operator; tier-2 `received_at` order as fallback |

### Forgejo Forks — Evaluated

Forgejo supports forks via `POST /repos/{owner}/{repo}/forks` (REST API) and a fork button in the UI. Forks are independent repos with their own issue tracker, branches, and PRs. They can open PRs against the parent repo.

### Alternative Architecture: Trunk + Machine-Controlled Forks

An alternative to the shared-event-log model: make tier-2 the canonical trunk, and give each machine its own fork of the trunk. Each machine writes comments to its fork, not the trunk. The trunk only receives consolidated git state (branches, commits, merged PR metadata), not every machine's comment thread.

When sync detects divergent comment paths (two machines commenting on the same issue independently), it splits them into separate issues on tier-2 rather than trying to merge the threads.

**What this solves:**

- Comment branching disappears — each machine's comments live in its own fork, no interleaving
- No per-node event log naming needed — forks are naturally namespaced
- Trunk is clean — only git state and merged metadata
- Phone sees a clean trunk without machine-scoped noise

**What it breaks:**

- **Forgejo forks don't share issues.** An issue in MacBook's fork is NOT the same issue as an issue in the trunk or in Linux's fork. There's no cross-fork issue linking. The operator sees scattered issues across N+1 repos.
- **The operator loses unified state.** "What's the status of issue #42?" depends on which fork you're looking at. The trunk might show "open" while MacBook's fork shows it closed with a comment.
- **Every issue splits by default.** Since machines can't share issues across forks, every issue the operator creates on MacBook exists ONLY in MacBook's fork. There is no "same issue on multiple forks" — the issue IDs are different repos.
- **Sequential workflow degraded.** The common case (operator works on MacBook, then moves to Linux) is worse — comments from the MacBook session live in MacBook's fork, invisible on Linux unless the operator navigates to a different repo.
- **Phone writes orphaned.** The phone comments on the trunk, but machine comments are in forks. Comments on the same topic live in three different places.
- **The "split out" trigger is unclear.** What constitutes divergent? Every comment from a different machine is in a different fork — all comments "diverge" by default. There's nothing to detect; the split is structural, not behavioral.
- **Fork PRs create admin overhead.** For changes to flow back to the trunk, the operator must open PRs from each fork, review them, and merge — the full multi-repo fork workflow for what should be a single-project experience.

**Verdict: the fork model makes the common case (sequential multi-machine work) worse while solving only the rare case (simultaneous offline work).** Most of the time, the operator works on one machine, syncs, then works on another. The shared-issue model handles this; the fork model degrades it.

### Middle Ground: Manual Splits, Not Structural Forks

Keep the current architecture (shared issues, merged comments) but add a **split command** in the Cove command center. If the operator notices misleading comment ordering (two machines wrote interleaved comments while offline), they can manually split the issue: "create two issues — one for MacBook's thread, one for Linux's thread." The sync layer preserves manual splits and reuses the issue prefix/directory structure. The split is an operator decision, not an automatic behavior.

This preserves the common case (clean sequential sync) while giving the operator a tool for the rare case (confusing interleaving from simultaneous offline work).

### Offline-First

The operator can:
- Shut down tier-2 (it's a standby, not a prerequisite)
- Disconnect MacBook from the network
- Work on MacBook for days
- Open PRs, comment, change labels, close issues
- All events are committed to the local sync repo

When they bring tier-2 back online (or MacBook reconnects to tier-2):
- MacBook local sync daemon pushes accumulated events to tier-2
- Tier-2 applies them, exposes them
- Any events from Linux box (or phone) that happened during the offline period are pulled
- Both sides converge

No data loss. No merge conflicts on most fields. The operator's offline work is preserved and synced.

### Event Identity and Uniqueness

Every event is authored by the same operator. But events from different nodes must be globally unique to avoid collisions when merged on tier-2. Include a node identifier and a node-local sequence number:

```json
{
  "id": "macbook-evt-042",
  "type": "comment.add",
  "issue": 42,
  "author": "cristos",
  "timestamp": "2026-06-13T10:15:00Z",
  "body": "I can reproduce this on M2 MacBook Pro."
}
```

The `id` is `{node_id}-evt-{seq}` where `node_id` is a short string (e.g., `macbook`, `linux`, `server`) unique to each local node, and `seq` is a monotonically increasing counter per node. This guarantees global uniqueness across all nodes without coordination.

Comment files follow the same pattern: `{seq}-{node_id}-cristos-{timestamp}.json`. Two nodes that generate comment `042` at the same second produce different filenames: `042-macbook-cristos-2026-06-13T10-15Z.json` vs `042-linux-cristos-2026-06-13T10-15Z.json`. Merging the sync repos is a clean union — no overwrite, no conflict.

### Git Push Races on Tier-2

Two locals pushing to the same sync repo on tier-2 simultaneously will cause one to get a non-fast-forward rejection. The sync daemon must handle this:

1. Try `git push`
2. If rejected (non-fast-forward), `git pull --rebase`
3. Rebase applies the other node's commits cleanly (comment files are additive, no conflicts)
4. Retry `git push`

For the hub-and-spoke model, this is the only coordination the sync daemon needs. One retry loop per push. With a handful of machines, contention is rare and the retry is fast (git pull + rebase + push < 1 second).

### Sync Repo: Shared or Per-Node?

Each project gets one sync repo on tier-2. All local nodes push to and pull from the same repo. This is simpler than per-node repos (which would require tier-2 to aggregate) and matches the git workflow the operator already uses — one remote, multiple contributors (the operator's own machines).

### Forgejo API Integration

The sync daemon reads and writes Forgejo state via its REST API. Forgejo provides a Swagger-documented API at `https://instance/api/swagger` with stable endpoints across each major version. The key endpoints for PR/issue sync:

| Operation | Endpoint | Auth |
|-----------|----------|------|
| List issues | `GET /repos/{owner}/{repo}/issues` | Token (scoped to repo) |
| Get issue | `GET /repos/{owner}/{repo}/issues/{idx}` | Token |
| Create issue | `POST /repos/{owner}/{repo}/issues` | Token (write) |
| Edit issue | `PATCH /repos/{owner}/{repo}/issues/{idx}` | Token (write) |
| List PRs | `GET /repos/{owner}/{repo}/pulls` | Token |
| Get PR | `GET /repos/{owner}/{repo}/pulls/{idx}` | Token |
| Create PR | `POST /repos/{owner}/{repo}/pulls` | Token (write) |
| List comments (issue) | `GET /repos/{owner}/{repo}/issues/{idx}/comments` | Token |
| Create comment | `POST /repos/{owner}/{repo}/issues/{idx}/comments` | Token (write) |
| List PR reviews | `GET /repos/{owner}/{repo}/pulls/{idx}/reviews` | Token |
| List labels | `GET /repos/{owner}/{repo}/labels` | Token |
| List reactions | Part of comment/issue response body | Token |

All endpoints use `Authorization: token {sha1}` headers. Tokens are scoped per-repo (generated via `POST /users/{name}/tokens`). Pagination is cursor-based with `page` and `limit` parameters, defaulting to 30 items per page, max 50. The sync daemon needs a `read:issue` + `write:issue` token for each repo on each instance.

**Detection strategy:** webhooks, not polling. Configure Forgejo to fire a webhook to the sync daemon on issue/PR/comment events. Each event has a payload with the affected resource ID and action. The sync daemon then fetches the full resource via API (for completeness — the webhook body may be truncated). Webhooks are more efficient than polling and give near-real-time sync.

**Bulk export for initial sync:** `GET /repos/{owner}/{repo}/issues` and `GET /repos/{owner}/{repo}/pulls` with pagination to export all state from local. Import to tier-2 with `POST` endpoints. Initial sync is a one-time import; after that, webhook-driven incremental.

**Write path (events to Forgejo):** when the sync daemon receives an event that creates/modifies an issue or comment, it calls the corresponding POST/PATCH endpoint on the target Forgejo. If the target Forgejo already has the event (idempotency check via event log position), skip. If the event fails (API error), retry with backoff.

**Scope note:** Forgejo projects (kanban boards) have limited API support as of 2025 — a merged PR adds basic project management via REST. Reactions, milestones, and fine-grained assignee management are available. The sync daemon doesn't need to cover every Forgejo feature in v1 — issues, PRs, and comments are the core.

## What This Doesn't Solve

- **Real-time sync** — sync is eventual, not real-time. Local events are visible on tier-2 within seconds; tier-2 events (from phone or other locals) are visible on local within the next pull cycle (default 60 seconds).
- **Conflict resolution for rapid simultaneous edits** — if the operator edits the same issue title on MacBook and Linux within seconds, last-writer-wins by timestamp. The "loser" sees a brief flash before the "winner" overwrites. Acceptable for solo dev.
- **Rich text / attachments** — comments can include images, attachments, mentions. All need to be encoded as files in the sync repo. The format handles this but adds complexity.
- **Forgejo-specific features** — reactions, project boards, milestones, labels with descriptions — all need explicit support in the event format. The format is extensible but each feature needs an event type.
- **External collaborators** — this design does not support friends, reviewers, or other people. If the operator needs to share a PR with someone, they push to a public forge (out of scope for this musing) or share a read-only tier-2 URL.

## Why This Differs from Existing Forgejo PR Mirroring Tools

The cove troves document the `forgejo-pr-mirror` research [synthesis](../../docs/troves/forgejo-pr-mirror/synthesis.md). The fundamental finding: **Forgejo's API cannot create real PR objects from external sources where the source branch doesn't exist on the target instance.** This kills Forgejo ↔ GitHub PR sync, and every existing tool works around it:

- **Forgesync** — one-way metadata sync (Forgejo → GitHub). PR state as metadata, not full conversation threads.
- **Gitea Mirror** — GitHub PRs imported as "enriched issues" with labels, not native PRs with diff/merge.
- **Forgejo issue #7556** (full two-way mirroring) — opened April 2025, no activity, not on roadmap.

Multi-stage cove avoids this limitation entirely because **branches exist on both instances**. The sync layer mirrors git refs (branches are everywhere), so when tier-2 calls `POST /repos/{owner}/{repo}/pulls` with `head: "macbook/feature-x"`, that branch already exists on tier-2. This is a standard Forgejo PR creation, not a cross-forge PR import. The API works.

Forgejo ↔ Forgejo sync with co-located branches is a different problem than Forgejo ↔ GitHub sync with absent source repos. The trove confirms no existing tool solves this, but the technical limitation (missing source branches) doesn't apply to our case.

Forgejo federation (ActivityPub/ForgeFed) is in progress. As of late 2025:
- **Stars federation** is built
- **User following** via ActivityPub has a merged PR passing end-to-end tests
- **PR/issue federation** is future work

The federation model assumes **one user, one home instance** — federation is for many operators across many instances. Our use case is **one operator, multiple home instances** — the same person with multiple primary forges. This isn't a supported federation pattern. The user model would fight us: each instance thinks its user is the canonical one.

Building atop federation would mean either:
- Waiting for upstream to add the pattern (multi-year, out of our control)
- Forking Forgejo to add it (significant maintenance burden)
- Implementing our own sync layer anyway (defeats the purpose)

Git-based event log sync sidesteps federation entirely. We don't need Forgejo to understand it — we just read/write the database via Forgejo's API and sync via our own protocol.

## Why Not Database Replication

SQLite (used by local Cove) supports some replication modes, but multi-master is not one of them. Replicating Forgejo's database directly would require:
- Single-writer (only one instance accepts writes at a time)
- Or conflict resolution at the database level (not Forgejo's domain)

Single-writer defeats the offline-first guarantee: if tier-2 is the single writer, locals can't work offline and sync back. Database-level conflict resolution is a much harder project than application-level event log sync.

## Critical Evaluation

The prior version of this musing was written by an agent that got the facts right but missed the soul. It built a distributed database on top of git and called it a sync protocol. It was thorough, correct on the technical details, and architecturally wrong for Cove.

### What It Got Right

1. **Offline-first as immutable.** Local Coves must work fully without tier-2. This is Cove's guiding principle applied correctly.
2. **Single-operator identity.** One account (`cristos`) everywhere. No RBAC, no ghost users, no `[bot]` convention. Matches Cove's "one person" constraint.
3. **PR/issue sync as the core problem.** Git sync is solved (Forgejo push mirrors handle it). PRs, issues, and comments are the actual feature. This framing is correct.
4. **Forgejo federation doesn't help.** Federation is for many operators across instances. We have one operator across instances. Different problem.
5. **Branch-mirroring advantage.** Existing tools fail because source branches don't exist on the target. Our architecture mirrors branches, avoiding this entirely.
6. **The fork model is wrong.** Correctly evaluated and rejected. Forks fragment issues across repos, degrade the sequential workflow, and don't solve anything the shared model doesn't solve better.

### What It Got Wrong

**1. The event log is over-engineered.** Per-node event logs, immutable comment files, a replay engine, mapping.json for ID translation — this is a full event sourcing system built on git. Cove's PURPOSE says "if it needs you to configure three things before it runs, it is not done." The event log requires configuring: sync repos, daemon processes, webhook endpoints, ID mapping, replay engines. That's five things before it runs. The musing built a distributed database and used git as the replication layer.

**2. Git is the wrong transport for operational data.** PRs and issues change frequently, have mutable state, and need arbitrary queries. Git is for immutable, content-addressed, branch-merging workflows. The musing acknowledged this without confronting it: "No meta.json is committed because two nodes would conflict on it." That's the data model telling you it doesn't fit the transport.

**3. The sync daemon is essentially a distributed database.** Event sourcing, replay, conflict resolution, ID mapping, multi-master convergence — all on top of git. Cove's PURPOSE says "opinionated" — Cove makes choices so you don't have to. The musing didn't make a choice; it invented a new distributed database protocol and called it "sync."

**4. Missing: the simplest thing that could work.** The musing leapt to event sourcing without considering direct API sync. Local Forgejo has a REST API. Tier-2 Forgejo has a REST API. A process that reads from one and writes to the other, bidirectionally, with last-writer-wins for conflicting mutations. No event logs, no git transport for operational data, no replay engine. Stateless. Restartable from scratch at any time.

**5. Missing: what Forgejo already provides.** Forgejo has built-in push mirrors for git. It has webhooks for event detection. It has a full REST API for issues/PRs/comments. The musing proposed a parallel system instead of using what Forgejo already gives.

**6. Missing: the harbor principle applied to tier-2.** Cove is a harbor — one command, everything inside. The musing treats tier-2 as a sync target but doesn't establish that tier-2 IS a Cove instance. If tier-2 is also a Cove, then `cove up` on tier-2 gives you Forgejo + Vault + runner + registry + pages. The sync is between two Cove instances, not between a Cove and a bespoke sync target.

**7. The phone is overspecified.** PURPOSE says "single developer does not mean single machine." Any device on the Tailscale network can access any Cove instance directly. The phone doesn't need tier-2 as a special case — it can hit the laptop's Cove via Tailscale when the laptop is online. Tier-2 is for when no laptop is online. The phone case is "access my Cove from elsewhere," not "access a special tier-2 Cove."

**8. The race conditions are self-inflicted.** R1-R8 are thorough, but most are problems created by the event log architecture, not inherent to multi-stage Cove. A simpler architecture (direct API sync) has fewer races because there's no intermediate representation to get out of sync.

## Alternative Approaches

Five approaches that supplement the event-log findings:

### A1. Direct API Sync (Bidirectional Forgejo API Bridge)

Forget event logs. A daemon reads issues/PRs/comments from one Forgejo instance via REST API and writes them to another. Bidirectional. Last-writer-wins for conflicts (compare `updated_at` timestamps). No event logs, no git transport for operational data, no replay engine. Git handles branches/commits via Forgejo's built-in push mirrors. The API bridge handles issues/PRs/comments.

**Advantage:** Stateless. Restart from scratch at any time by re-reading the source. No mapping.json, no per-node logs, no replay. Forgejo is the source of truth on each instance; the bridge keeps them consistent.

**Challenge:** Detecting changes. Poll the API (simple but wasteful) or webhooks (efficient but require the daemon to be reachable). For offline-first, webhook delivery fails when the target is down. Polling with `since` timestamps is more robust.

### A2. Forgejo Database Sync (SQLite Replication)

Instead of building a parallel system, sync Forgejo's own SQLite databases. Forgejo uses one SQLite file per repo. Rsync or Litestream could replicate these files. Application-level conflict resolution (last-writer-wins on rows) when both instances modified the same issue.

**Advantage:** No custom event format, no mapping, no API bridge. Forgejo stays the source of truth. The sync layer is a file-level operation with row-level conflict resolution.

**Challenge:** SQLite is not designed for multi-master replication. Two instances writing to the same DB file will corrupt it. The replication would need to be stop-sync-start: stop Forgejo on both sides, sync the DB files, restart. This defeats "always available."

### A3. ForgeFed as Transport (Repurposed)

Forgejo's federation layer uses ActivityPub for inter-instance communication. Even though it's designed for multi-operator, the transport and object model (Ticket, Comment, Review) could be repurposed for same-operator multi-instance. All instances trust all others because they're all `cristos`.

**Advantage:** Leverages Forgejo's own federation work. Standard object types. No custom event format.

**Challenge:** ForgeFed is incomplete (as of late 2025, only stars federation is built). Building on an incomplete foundation means either waiting or contributing upstream. And the trust model is wrong — ForgeFed assumes different operators, so it has authentication and authorization that we'd need to bypass or simplify for same-operator use.

### A4. Shared Storage (NFS/SMB Mount)

All local Coves share the same Forgejo data directory on tier-2 via network mount. Only the active instance writes. Needs a coordination layer (which Cove is active?) but eliminates sync entirely — there's one database.

**Advantage:** No sync protocol at all. One Forgejo instance, one set of data.

**Challenge:** Requires network connectivity for writes. Defeats offline-first. Only works for the "always-online tier-2" use case, not the "laptop in a café" use case. Also, SQLite over NFS is famously unreliable. This approach is a non-starter for Cove's offline-first principle.

### A5. Single Forgejo, Multiple Git Remotes

Run one Forgejo on tier-2. Local machines push/pull git directly (via SSH/HTTPS). Issues/PRs/comments live on tier-2 only. When offline, local machines work on git branches and accumulate local commits. When online, they push. The "multi-stage" problem reduces to "how do I use Forgejo when offline" — which Cove already handles (local git works offline, Forgejo is read-only until you're back online).

**Advantage:** Simplest possible architecture. No sync protocol. One Forgejo. Issues and PRs are always in one place.

**Challenge:** No offline issue/PR creation. If you want to file an issue while offline, you can't — Forgejo is on tier-2 and you can't reach it. This is the core use case that multi-stage Cove is supposed to solve. This approach reduces multi-stage Cove to "git push from multiple machines," which is already solved.

## Going in a Different Direction

Two alternatives that rethink the problem entirely:

### D1. Don't Sync Forgejo — Build a Cove-Native Issue Tracker

The hardest part of multi-stage is Forgejo's issue/PR model (no threading, no external API for creating real PRs from absent branches, SQLite-only). Why fight it? Build a Cove-native issue tracker that stores issues in git (like git-bug) and renders them in a web UI. No Forgejo API to fight, no database to sync, no event log to replay. Issues are git objects, synced the same way branches are synced. Comments are files in the repo. PR metadata (title, body, labels, state) are files too. The web UI reads from the git repo and renders issues/PRs.

This makes multi-stage trivial: `git push` already handles distribution. The issue tracker is just another git-based tool. No daemon, no sync protocol, no mapping.

**Advantage:** Eliminates the entire sync problem. Git IS the sync. Offline-first by construction.

**Challenge:** You lose Forgejo's issue/PR UI and all its features (reviews, CI integration, merge buttons). You'd need to build a web UI that's good enough to replace Forgejo's. That's a significant product investment. And you'd need a PR creation flow that creates real Forgejo PRs (with diff, merge) from git data, which brings back the API limitation.

### D2. Don't Multi-Stage — Single Instance, Remote Access

Instead of N Forgejo instances, run one Forgejo (on tier-2 or on the laptop) and access it from everywhere via Tailscale.

**This is wrong for Cove's primary use case.** Cove is for "someone who writes code on planes, in cafés, at cabins." The laptop being offline — lid closed, asleep in a bag, on a plane with WiFi off — is the NORMAL mode, not an edge case. D2 solves phone access and always-on availability but fails the airplane test. The operator can't create issues, comment on PRs, or see CI status when the laptop is offline and Forgejo is on tier-2.

D2 is not a viable starting point. It solves the wrong problem.

## Decomposing Further: Maybe Forgejo Isn't Where Issues Should Live

The core tension: Forgejo's data model (SQLite, flat comments, no threading) is not designed for distributed sync. Every approach that syncs Forgejo instances fights Forgejo's architecture. What if we stop fighting it?

### D3. Separate the Concerns: Forgejo for Git + PRs, Git-Based Tracker for Issues

Forgejo handles what it's good at: git hosting, PRs (which are git operations — branches, diffs, merges), and CI status display. Issues and comments move to a **git-based issue tracker** that's designed for distributed sync from the ground up.

**What already exists:** This isn't a greenfield build. The most mature option is **[git-bug](https://github.com/git-bug/git-bug)** (v0.10.1, May 2025, 9.9k stars, active development as of 2026). It's a standalone, distributed, offline-first issue tracker that embeds issues and comments as git objects in a separate ref namespace (`refs/bugs/`). It has:
- CLI, TUI (`git bug termui`), and a web UI (`webui/`)
- Bridges to GitHub and GitLab for bidirectional sync
- Conflict-free merge by construction (issues are stored as edit operations in git blobs, assembled in a linear chain of commits)
- Go binary, single-file install, no database

Other options: **git-issue** (dspinellis, decentralized issue management), **bug** (driusan, filesystem-based with `issues/` directory), **Fossil** (built-in issue tracker but not git-based — would replace git entirely).

git-bug is the right fit. It's already what D3 describes: a git-based issue tracker that's offline-first, distributed, and syncs via `git push`/`git pull`. No custom protocol, no event log, no daemon. The question isn't "build or buy" — it's "integrate git-bug alongside Forgejo."

**How it works:**

- **Tier-2** runs Forgejo (git hosting, PRs) + git-bug web UI (issue tracking)
- **Local machines** run git (for code) + git-bug CLI (for offline issue work)
- **Phone** accesses tier-2's git-bug web UI for issues, tier-2's Forgejo for PRs
- **Sync:** `git push` / `git pull` on the bug repo. Same as code. No daemon.

```
┌─ local machine (MacBook, offline) ─┐
│  git: code repos                    │
│  git-bug: issue tracker             │──┐
│  (create issues, comment, close)    │  │
└─────────────────────────────────────┘  │
                                         │ git push/pull (when online)
┌─ local machine (Linux, offline) ────┐  │
│  git: code repos                    │──┤
│  git-bug: issue tracker            │  │
│  (create issues, comment, close)    │  │
└─────────────────────────────────────┘  │
                                         ▼
┌─ tier-2 (always online) ───────────────┘
│  Forgejo: git hosting, PRs            │
│  git-bug web UI: issue tracking       │
│  (both read from the same git repos)  │
└───────────────────────────────────────┘
                    ▲
                    │ HTTPS
┌───────────────────┴────┐
│  Phone (browser)      │
│  git-bug web UI       │
│  Forgejo web UI       │
└───────────────────────┘
```

**What this solves:**

- **Offline-first by construction.** git-bug stores issues in git. Git works offline. Create issues, comment, close — all work offline. Sync when online via `git push`.
- **No Forgejo API to fight.** Issues are git objects, not rows in Forgejo's SQLite. No API calls, no webhooks, no event logs.
- **No sync protocol to build.** Git IS the sync protocol. git-bug already uses it.
- **No sync protocol to build.** Git IS the sync protocol. git-bug already uses it.
- **No mapping.json.** Issues have stable IDs (git object hashes). No per-instance numeric ID translation.
- **No race conditions beyond git's own.** git-bug's storage model (edit operations in a linear commit chain) is conflict-free by design.
- **Existing project, active community.** 9.9k stars, 2,627 commits, v0.10.1 released May 2025. Not a prototype — a real tool.

**What this loses:**

- **Split UX.** Issues live in git-bug's web UI. PRs live in Forgejo's web UI. The operator switches between two interfaces. This is the main cost.
- **Cross-references.** A commit message saying "closes #42" needs to reference git-bug's issue ID, not Forgejo's. This is a convention, not a technical problem, but it needs to be consistent.
- **PR comments.** Inline code review comments live in Forgejo. General PR discussion could live in git-bug. This split needs a clear UX convention.
- **CI status on issues.** If CI runs locally and reports to Forgejo, git-bug needs to display CI status from Forgejo. Cross-system data flow or skip for v1.
- **git-bug maturity.** v0.10.1 is pre-1.0. The API may change. The web UI may not be polished enough for phone use. Need to evaluate before committing.

### git-bug + Forgejo PR Integration

git-bug has **no PR support at all** — no PR entity type, no PR data model, no PR workflow. This is by design: git-bug is an issue tracker, and PRs are code review workflows that belong in the forge. The integration needs to bridge these two systems.

#### What Lives Where

| Concern | Lives In | Why |
|---------|----------|-----|
| Issue tracking (bugs, features, tasks) | git-bug | Offline-first, distributed, syncs via git |
| PR metadata (branch, diff, merge status) | Forgejo | Forgejo is the git host; PRs are git operations |
| PR inline code review (comment on specific lines) | Forgejo | This is a code review feature, not an issue feature |
| PR general discussion (should we merge? design feedback) | git-bug | This is issue-style discussion, belongs in the tracker |
| CI status | Forgejo | CI reports to Forgejo via webhooks |
| Labels | git-bug | git-bug has full label support |
| Milestones | git-bug (when implemented) | git-bug doesn't have milestones yet; track them as labels for v1 |
| Assignees | Forgejo | git-bug doesn't have assignees; single-operator doesn't need them |

#### Linking Issues and PRs

A PR in Forgejo references an issue in git-bug by convention. Three approaches:

**Approach 1: Forgejo metadata.** The PR description contains a reference like `git-bug: abc1234` (using git-bug's human-readable ID). A Cove-side hook reads this reference and links the PR to the issue in the web UI. Simple, but requires manual entry.

**Approach 2: git-bug metadata.** When a PR is created in Forgejo, a git-bug issue is automatically created with a `SetMetadataOp` linking it to the Forgejo PR URL (`forgejo-pr-url=https://git.cove/owner/repo/pulls/5`). This is how git-bug's bridges work — they use metadata to track the mapping between local and remote entities. The git-bug issue becomes the discussion thread for the PR.

**Approach 3: Both.** git-bug metadata links the issue to the PR, and Forgejo's PR description links back to the git-bug issue. Bidirectional linking via Cove's web UI or a small bridge daemon.

**Recommendation: Approach 2 for v1.** git-bug's metadata system already exists and is designed for exactly this. The bridge daemon creates a git-bug issue when a Forgejo PR is opened, links them via metadata, and the operator discusses the PR in git-bug's issue (which syncs offline). Inline code review stays in Forgejo.

#### Bridge: Forgejo Actions (Not a Daemon)

Instead of a separate daemon, use Forgejo Actions to create git-bug issues when PRs are opened. Forgejo Actions supports `pull_request` events (opened, synchronized, closed) and the automatic token has write permission to the repository. A Forgejo Action can run `git bug` commands directly — no separate daemon needed.

```yaml
# .forgejo/workflows/bug-sync.yaml
name: Bug Sync
on:
  pull_request:
    types: [opened, closed, reopened]
jobs:
  sync:
    runs-on: docker
    steps:
      - uses: actions/checkout@v4
      - name: Install git-bug
        run: |
          curl -sL https://github.com/git-bug/git-bug/releases/latest/download/git-bug_linux_amd64.tar.gz | tar xz
          sudo mv git-bug /usr/local/bin/
      - name: Create bug for new PR
        if: github.event.action == 'opened'
        run: |
          git bug bug new \
            -t "PR: ${{ github.event.pull_request.title }}" \
            -m "Discussion for PR #${{ github.event.pull_request.number }}" \
            -l pr
          git bug push
      - name: Close bug when PR closes
        if: github.event.action == 'closed'
        run: |
          BUG_ID=$(git bug bug -f id -l pr --no | head -1)
          if [ -n "$BUG_ID" ]; then
            git bug bug status close "$BUG_ID"
            git bug push
          fi
```

This is simpler than a daemon — no process to manage, no webhook endpoint, no routing. The Action runs on Forgejo's CI runner (which Cove already provisions), has access to the repo, and can push bug refs directly.

**Conversely: if an issue starts with `PR:`, create a Forgejo PR.** The inverse direction — git-bug issue → Forgejo PR — can also work via a Forgejo Action triggered by `push` to `refs/bugs/`. When a new bug is created with a title matching `PR: {title}`, the Action can use the Forgejo API to create a corresponding PR. But this requires knowing the branch, which isn't in the bug title. A better approach: the operator creates the branch first, then the bug with `forgejo-branch: feature-x` metadata. The Action reads the metadata and creates the PR.

**For v1, start with the one-way bridge (PR opened → git-bug issue).** The inverse (bug → PR) can wait until the workflow is proven.

Events the bridge handles:

| Forgejo Event | git-bug Action |
|---------------|----------------|
| PR opened | Create git-bug issue with title, body, `forgejo-pr-url` metadata, `pr` label |
| PR closed (not merged) | Close git-bug issue |
| PR merged | Close git-bug issue, add `merged` label |
| PR title updated | Update git-bug issue title |
| PR labels changed | Sync labels to git-bug issue |

The bridge does NOT sync:
- PR inline code review comments (stay in Forgejo)
- PR diff/merge operations (stay in Forgejo)
- CI status (stays in Forgejo)

This is a one-way bridge (Forgejo → git-bug). The operator creates issues in git-bug (which syncs offline) and discusses PRs in git-bug issues (which also syncs offline). Forgejo is the source of truth for PR state; git-bug is the source of truth for discussion.

#### Offline PR Creation

When the operator creates a PR offline (on a plane), the workflow is:

1. Push the branch to Forgejo (when online) — `git push cove feature-x`
2. Create the PR in Forgejo — `fj pr create "feature-x"`
3. The bridge creates a git-bug issue for the PR

But what if the operator wants to start discussing a PR while offline? They can:

1. Create a git-bug issue with a `pr` label and a title matching the branch name: `git bug bug new -t "feature-x: refactor vault" -m "PR discussion for feature-x"`
2. Add `forgejo-branch: feature-x` metadata to the issue
3. When online, create the PR in Forgejo, and the bridge links the existing git-bug issue to the new PR

This is manual but works. A future improvement could detect branches with matching names and auto-link.

#### Forgejo Bridge for git-bug

git-bug already has a Forgejo/Gitea bridge in progress (PR #1565, draft, import-only). This bridge syncs Forgejo issues to git-bug. For Cove, we need:

1. **Import (Forgejo → git-bug):** Already in progress via PR #1565. Handles issues, comments, labels, status.
2. **Export (git-bug → Forgejo):** Not yet built. Needed for v1 if we want git-bug issues to also appear in Forgejo's issue tracker (for phone access via Forgejo's web UI).
3. **PR sync (Forgejo → git-bug):** New. Creates git-bug issues for Forgejo PRs with metadata linking.

The import bridge (PR #1565) gives us Forgejo issue → git-bug sync. We'd need to add export and PR sync. The export is the harder part — it needs to create Forgejo issues from git-bug bugs, handle comment creation, and keep state in sync.

**For v1, we may skip export.** The operator accesses issues via git-bug's web UI on tier-2 (phone-friendly) and git-bug CLI (local, offline). Forgejo's issue tracker is secondary. If the operator never uses Forgejo's issue UI, export is unnecessary.

#### Identity Mapping

git-bug has its own identity system (stored in `refs/identities/`). Forgejo has its user system. For Cove's single-operator use case, these are trivially mapped: one identity (`cristos`) in git-bug, one account (`cristos`) in Forgejo. The bridge maps them by name/email.

#### Sync Topology (Updated for git-bug)

```
┌─ local machine (MacBook, offline) ─┐
│  git: code repos                    │
│  git-bug: issue tracker             │──┐
│  (create issues, comment, close)    │  │
└─────────────────────────────────────┘  │
                                         │ git push/pull (when online)
┌─ local machine (Linux, offline) ────┐  │
│  git: code repos                    │──┤
│  git-bug: issue tracker            │  │
│  (create issues, comment, close)    │  │
└─────────────────────────────────────┘  │
                                         ▼
┌─ tier-2 (always online) ───────────────┘
│  Forgejo: git hosting, PRs, Actions   │
│  git-bug web UI: issue tracking       │
│  Forgejo Action: PR → bug linking     │
└───────────────────────────────────────┘
                    ▲
                    │ HTTPS
┌───────────────────┴────┐
│  Phone (browser)      │
│  git-bug web UI       │
│  Forgejo web UI       │
└───────────────────────┘
```

No separate daemon needed. Forgejo Actions run `git bug` commands when PRs are opened/closed, creating and updating git-bug issues automatically.

**The key insight: git already solves distributed sync.** The problem is that Forgejo's issue/PR data doesn't live in git. git-bug already solved this — it stores issues in git. By using git-bug alongside Forgejo, we inherit git's distributed sync for free. Forgejo keeps doing what it's good at (git hosting, PRs, CI) without being forced into a sync model it wasn't designed for.

### Branching Comment Threads: Edge Case, Not Architecture Driver

The musing's race condition analysis (R5) spends significant effort on comment branching — two machines writing comments offline that interleave misleadingly when merged. This is a real problem, but for a single operator it's an edge case, not an architecture driver.

**Why it's low likelihood:**
- Single operator works on one machine at a time. Simultaneous offline work on two machines is rare.
- NTP keeps clocks close enough that the order approximates wall-clock intent.
- The operator wrote all the comments. They know what they meant.

**Note: git-bug also has flat comments (no threading).** This is the same constraint as Forgejo. But git-bug uses Lamport clocks for ordering, which provides a deterministic total order regardless of concurrent edits. Two machines writing comments offline will have a deterministic order after sync — not necessarily wall-clock order, but a consistent order that both machines agree on. This is better than Forgejo's `created_at` timestamps, which depend on wall clocks.

**How to handle it as an edge case:**
- **Do nothing.** The operator sees the interleaved order, recognizes it's misleading, and moves on. They wrote the comments — they know the context.
- **Clarifying comment.** The operator adds "To clarify, I wrote the above before seeing the Linux box's comment." Simple, human, works.
- **Lamport clock ordering.** git-bug's Lamport clocks provide deterministic ordering. After sync, both machines agree on the order. It may not match wall-clock intent, but it's consistent and unambiguous.
- **Edit/delete.** git-bug supports comment editing and deletion. If the ordering is truly confusing, the operator can edit or delete comments.

None of these require a custom event log, per-node event streams, or a replay engine. The simplest fix — a sync annotation — is a single field in the comment metadata. The event-log architecture was solving a problem that doesn't need solving at the architecture level.

### D4. Email-Based Issue Workflow

Before web-based forges, open source development ran on email. Patches were emailed. Bug reports were emailed. Discussion happened on mailing lists. Email is offline-first by design — you compose offline, send when connected, receive when connected.

**How it works:**

- Issues are filed by emailing a dedicated address on tier-2
- Comments are replies to the email thread
- PRs are email patches (git format-patch / git send-email)
- Local machines use their email client for issue/PR workflow
- Tier-2 runs a mail-to-issue bridge that converts emails to Forgejo issues/PRs
- Phone uses its email client (already installed) for reading and replying

**Advantage:** Email is the most battle-tested offline-first communication protocol. Every device has an email client. No sync daemon, no event log, no custom protocol. The operator composes an issue on the plane, it sends when the laptop reconnects.

**Challenge:** Email threading is primitive (subject-line-based). Forgejo's flat comment model maps well to email (each reply is a new comment), but the UX is worse than a web UI. And email patches (git send-email) are a different workflow from Forgejo PRs — the operator would need to learn a new PR workflow or the bridge would need to create Forgejo PRs from emailed patches (which brings back the API limitation).

### D5. CRDT-Based Issue Sync

Instead of git or event logs, use CRDTs (Conflict-free Replicated Data Types) for issue/comment state. Each machine maintains a local CRDT store. Sync is a pairwise merge of CRDT state — no conflict resolution needed because CRDTs converge by construction.

**How it works:**

- Each issue is a CRDT document (title, body, labels, state, comments)
- Each comment is a CRDT within the issue document
- Local edits are applied immediately to the local CRDT store
- Sync is a CRDT merge between instances (push/pull the CRDT state)
- No conflict resolution, no last-writer-wins, no event log

**Advantage:** CRDTs eliminate the entire conflict resolution problem. No races, no branching, no last-writer-wins. The math guarantees convergence.

**Challenge:** CRDTs are complex to implement correctly. The CRDT store needs to be embedded in the sync daemon (or use an existing library like Automerge or Yjs). CRDT state can grow large (every edit is preserved for merge history). And CRDTs don't integrate with Forgejo's SQLite — you'd still need a bridge to convert CRDT state to Forgejo API calls on tier-2.

## Where This Leaves Us

The event-log architecture is over-engineered. D2 (single instance) fails the airplane test. The most promising direction is **D3 (separate concerns)** — use **git-bug** alongside Forgejo. Forgejo handles git hosting and PRs. git-bug handles issues and comments. Git handles distributed sync for both.

D3's cost is a split UX (issues in git-bug's web UI, PRs in Forgejo's web UI) and the integration work (PR ↔ issue linking, CI status display). But the cost of the event-log approach is also a new component (sync daemon with event log, replay engine, mapping, webhooks) — and it fights Forgejo's data model the whole way. git-bug already solved the hard problem (distributed issue tracking in git). We don't need to build it.

Branching comment threads are an edge case, not an architecture driver. A sync annotation ("Written offline on MacBook, synced at...") is sufficient. No event log, no replay engine, no per-node event streams.

**Recommendation:** Evaluate git-bug. Install it, test the offline workflow, test the web UI on a phone. If the UX is acceptable, this is the architecture. If the split UX is too confusing, the event-log approach is the fallback — but it should be designed as a distributed database, not a git-based event system.

## Implementation Path (D3)

1. **Evaluate git-bug** — install on MacBook, test CLI (`git bug bug new`, `git bug bug comment new`), test TUI (`git bug termui`), test web UI (`git bug webui`). Verify offline workflow: create issues on the plane, push when online.
2. **Set up git-bug on tier-2** — run `git bug webui` as a system service behind Cove's nginx. This is the phone-accessible issue tracker.
3. **Set up git-bug on each local machine** — `git bug` CLI. Issues are stored in the code repo's `refs/bugs/` namespace (same repo, not a separate repo — issues travel with code).
4. **Configure sync** — `git bug push` / `git bug pull` on the bug refs. git-bug stores issues in `refs/bugs/` and identities in `refs/identities/`. These are pushed/pulled alongside code refs.
5. **Write Forgejo Action** — `.forgejo/workflows/bug-sync.yaml` that triggers on `pull_request` events and runs `git bug` commands to create/close/link git-bug issues. No separate daemon needed.
6. **Test offline convergence** — create issues on MacBook, push to tier-2, view on phone. Verify both sides converge.
7. **Test hub-and-spoke** — MacBook and Linux both sync to tier-2. Verify issues from both machines appear on tier-2 and on each other's next pull.
8. **Test PR → bug linking** — create a PR in Forgejo, verify the Action creates a corresponding git-bug issue with `pr` label and metadata.

## Open Questions (D3)

1. **Same repo or separate repo?** — git-bug stores issues in `refs/bugs/` within the code repo. Same repo means issues travel with code and are visible when you clone the project. Evaluate whether this is the right UX or whether a separate bug repo is better.
2. **PR ↔ issue linking** — Forgejo Action (PR opened → git-bug issue created with `pr` label and `forgejo-pr-url` metadata) for v1. Inline code review stays in Forgejo. General PR discussion lives in the git-bug issue.
3. **Inverse linking (bug → PR)** — if an issue starts with `PR:` or has `forgejo-branch:` metadata, should a Forgejo Action create the PR? Needs the branch to already exist. Deferred to v2.
4. **Phone workflow** — git-bug's web UI on tier-2 supports full CRUD (create, comment, label, close). The phone can create issues and comment. The web UI needs write access to the git repo on tier-2.
5. **Migration path** — existing Cove users have issues in Forgejo's SQLite. git-bug has a Forgejo/Gitea bridge in progress (PR #1565, import-only). A one-time migration script would read Forgejo's API and create issues in git-bug.
6. **CI status on issues** — Forgejo Action could add CI status as git-bug labels (`ci-passing`, `ci-failing`) or metadata. Cross-system but not complex. Skip for v1.
7. **git-bug maturity** — v0.10.1, pre-1.0. No milestones, no assignees, no PR support, no attachments in UI. The web UI is alpha. Evaluate whether these gaps are acceptable for v1.
8. **Forgejo Action authentication** — the Action needs to push bug refs back to the repo. The automatic `GITHUB_TOKEN` has write permission, but it needs `git bug` installed on the runner. Verify the runner image has git-bug available or add an install step.

## Next Steps

- Install git-bug on MacBook and test the full workflow (create, comment, close, push, pull, web UI)
- Evaluate git-bug's web UI on a phone browser
- Decide: same repo or separate repo for bug data
- Design `cove-bridge` webhook handler (PR events → git-bug issue creation)
- If git-bug passes evaluation, write a SPEC for the integration architecture
