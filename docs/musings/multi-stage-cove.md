---
title: "Multi-Stage .cove — Operator-Centric with Always-Online Tier-2"
created: 2026-06-13
authored-by: deepseek-v4-flash:cloud
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

## Why Not Forgejo Federation

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

## Implementation Path

1. **Define the event format** — JSON schema for issues, PRs, comments, reviews, labels, etc. Each event type has a clear shape.
2. **Build the local sync daemon** — watches Forgejo for changes, writes to the sync repo, commits, pushes to tier-2. Small Python service, runs alongside Forgejo.
3. **Build the tier-2 sync daemon** — pulls from each local's sync repo (or receives pushes), applies events to its Forgejo database. Same daemon, different config.
4. **Build the read path** — tier-2's Forgejo reads from its own database. No changes to Forgejo needed. The sync daemon is a separate process.
5. **Handle initial sync** — when tier-2 is first set up, bulk-export all issues/PRs from each local, import to tier-2. After that, incremental.
6. **Test offline convergence** — disconnect MacBook, work for a day, reconnect, verify both sides converge. This is the core invariant.
7. **Test hub-and-spoke** — verify MacBook and Linux box both sync to tier-2 without interfering with each other.

## Open Questions

1. **Sync trigger cadence** — push on every event, or batch every N seconds? Trade-off: latency vs. resource use.
2. **Conflict UX** — when last-writer-wins isn't clear, how do we present the choice to the operator? Inline in Forgejo? A separate `cove sync` command?
3. **Schema evolution** — when Forgejo adds a new field, how does the event format evolve? Versioned events, optional fields, migration scripts?
4. **Attachments and large content** — images, PDFs, large comments. Store in the sync repo (bloats git) or use content-addressed storage (CAS) with git storing only the hash?
5. **Tier-2 hardware** — Raspberry Pi? Old laptop? VPS? Each has different cost/uptime/trust trade-offs.
6. **Phone as a sync participant?** — currently the phone is read-only via HTTPS. Should it ever write? If the operator types a long comment on their phone, does that go through tier-2's normal event flow? (Answer: yes, tier-2 is the phone's only writer, so it's already in the flow.)
7. **What if tier-2 is down for a day?** — locals accumulate events locally. When tier-2 comes back, they push. No data loss. But phone access is unavailable during the outage.

## Next Steps

- Write a spec for the event format (SPEC: Multi-Stage Cove Sync Protocol)
- Prototype the sync daemon with a minimal event set (issues + comments)
- Test offline convergence with MacBook disconnected
- Test hub-and-spoke with MacBook and Linux both syncing to tier-2
- Decide on sync trigger cadence and conflict UX
- Plan migration path for existing local-only Cove users
