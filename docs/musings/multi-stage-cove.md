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
│   ├── 001-forge-crash-on-large-repos/
│   │   ├── meta.json       # title, body, state, labels, assignees, etc.
│   │   ├── comments/
│   │   │   ├── 001-cristos-2026-06-13T09-42Z.json
│   │   │   ├── 002-cristos-2026-06-13T10-15Z.json
│   │   │   └── ...
│   │   └── events.log      # append-only event stream
│   └── 002-slow-ci-on-arm/
│       └── ...
├── pulls/
│   ├── 042-refactor-vault-cache/
│   │   ├── meta.json
│   │   ├── commits.json    # the commits that make up the PR
│   │   ├── comments/
│   │   ├── reviews/
│   │   └── events.log
│   └── ...
└── refs/
    ├── heads/sync
    └── remotes/tier2/main
```

Each issue and PR has:
- A `meta.json` (current state — derived by replaying the event log)
- A directory of immutable records (comments, reviews, etc.) — each is a file, never edited, only added
- An `events.log` — append-only stream of state changes

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

### Conflict Resolution

Because each comment is an immutable file with a unique name (sequence + author + timestamp), two comments can never "conflict" — they're two distinct files. A merge of two sync repos is just a union of files. Git's three-way merge handles this cleanly.

The harder case is `meta.json` — multiple events changing the same field. Example: MacBook local changes the issue title at 10:00, Linux local changes the same issue's title at 10:05. The last-writer-wins by event timestamp. If timestamps are too close to call, the operator is shown both versions and chooses.

For most fields (title, body, state, labels), the latest event wins. For additive fields (assignees, labels), the union wins. For comments, no conflict — each is a separate file.

**Branch conflicts** are git's problem, not the sync layer's. If MacBook and Linux both push to `main`, fast-forward rules apply. Conflicting branches require manual merge on whichever local the operator is sitting at.

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

### Event Identity

Every event is authored by the same operator. No machine ID, no origin-instance ID, no bot suffix:

```json
{
  "id": "evt-001-cristos-2026-06-13T10-15Z",
  "type": "comment.add",
  "issue": 42,
  "author": "cristos",
  "timestamp": "2026-06-13T10:15:00Z",
  "body": "I can reproduce this on M2 MacBook Pro."
}
```

The author string is identical on every instance. Comment file names are identical too. The sync daemon doesn't need to translate, map, or remap anything.

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
