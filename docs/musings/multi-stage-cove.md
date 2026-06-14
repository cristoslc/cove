---
title: "Multi-Stage .cove — Local + Network with PR/Issue Sync"
created: 2026-06-13
authored-by: deepseek-v4-flash:cloud
status: Draft
---

# Multi-Stage .cove

## Hard Constraints

These are non-negotiable, set by the project worldview:

1. **PR/Issue sync is the whole point.** Without it, multi-stage is just "git push to a remote," which is trivial and solved. The hard part — keeping PRs, issues, and their comments in sync across two instances — is the actual feature.
2. **Offline-first is immutable.** The local Cove must work fully without the network Cove. Disconnected operation is the normal mode, not degraded mode.
3. **No public forge dependency.** No Codeberg, no GitHub, no shared external service. The operator owns both instances end-to-end.

These constraints eliminate the obvious solutions. Using a public Forgejo is out. Waiting for upstream federation is out (and it targets a different use case anyway). The network Cove must be a second self-hosted instance the operator controls.

## The Idea

Two self-hosted Cove instances, both owned by the operator:

- **Local Cove** (`git.cove`) — primary development surface, always available, fully offline-capable. Where the operator actually works.
- **Network Cove** (`git.example.com` or LAN address) — collaboration surface, accessible to collaborators and to the operator from other devices. Mirror of local, but accepts writes (PRs, issues, comments) from collaborators.

PRs, issues, and their comments must sync between the two. The operator works offline on local Cove, comes online, and the state syncs to network Cove. A collaborator comments on a PR via network Cove; the comment syncs back to local Cove.

```
┌─ local cove (git.cove) ──────────────────────┐
│  forgejo: full history                       │
│  runner: local CI                            │
│  vault: local secrets                        │
│  Pages: local preview                        │
└──────────────────┬───────────────────────────┘
                   │ PR/issue/comment sync
                   ▼
┌─ network cove (git.example.com) ─────────────┐
│  forgejo: collaboration surface              │
│  Pages: public preview                       │
│  (no runner, no vault — those stay local)    │
└──────────────────────────────────────────────┘
```

## Identity Model

Each machine gets its own account on its local Cove. The operator has one account on network Cove. Accounts on local Cove are machine-scoped; accounts on network Cove are person-scoped (operator + collaborators).

| Surface | Account | Scope |
|---------|---------|-------|
| Local Cove (MacBook) | `cristos-macbook` | Machine |
| Local Cove (Linux box) | `cristos-linux` | Machine |
| Network Cove | `cristos` | Operator (human) |
| Network Cove | `friend-alice` | Collaborator (human) |
| Network Cove | `cristos-macbook[bot]` | MacBook agent (synced from local) |
| Network Cove | `cristos-linux[bot]` | Linux box agent (synced from local) |

When the MacBook's AI agent opens a PR on local Cove, it appears on network Cove as authored by `cristos-macbook[bot]`. When the operator comments on network Cove from their phone, it syncs back to local Cove as authored by `cristos`. Identity is per-instance, not global.

This means there's no "the same person, two home instances" problem — there are different identities on each instance, and sync reconciles them by content (not by author).

### How Many Accounts Need to Exist on Local Cove?

Concretely: my laptop has one local Cove. The network forge has 5 accounts (`cristos`, `cristos-laptop`, `cristos-desktop`, `friend`, `friend-laptop`). How many of those need to be in my local forge?

**Answer: exactly one real account — the machine account for the machine local Cove is running on.**

| Identity on network | Needed on local? | Form |
|---------------------|------------------|------|
| `cristos-laptop` | No (it IS the local account) | The local machine account |
| `cristos-desktop` | No | Remote author metadata (name, avatar, link) |
| `cristos` | No | Remote author metadata |
| `friend` | No | Remote author metadata |
| `friend-laptop` | No | Remote author metadata |

Local Cove has **one real account** (`cristos-laptop` — the operator's identity on this machine). All other identities that appear in synced events are **remote authors** — metadata entries (name, avatar, link to their network profile) but not Forgejo accounts. They can't log in to local, they don't have local permissions, they're just labels for "who said this."

**Why not full accounts for remote authors?**
- They have no credentials on local (no login, no SSH key, no password)
- They don't act on local (no pushes, no PRs created locally, no admin actions)
- They don't need local permissions (read-only display is enough)
- Creating accounts for them creates the collision problem this model is designed to avoid

**Why is this safe?** Integrity comes from the sync channel, not from the accounts. When an event syncs from network to local, the local sync daemon verifies the event came from a trusted source (the network forge's sync repo, which only the operator can push to). The author field is just a display label. If someone compromises the network forge, they can impersonate anyone — but that's a network forge security problem, not a local identity problem.

**Special case: the operator's network identity (`cristos`).** When `cristos` comments from network, the comment syncs to local. The local operator (who is `cristos-laptop`) sees "comment by cristos" and knows it's themselves via network. The sync layer can optionally mark remote authors from the same operator as "you (via network)" for clarity, but the underlying data is just an author string.

**The exception: friends who also have a local Cove.** If `friend-alice` runs her own Cove and syncs to my network forge, her machine account (`friend-alice-laptop`) is a remote author on my local Cove. We are both the operator of our own forges, and our local forges sync to the same network forge. Neither of us has accounts on the other's local forge.

## Sync Architecture: Event Log via Git

PRs and issues are stored in Forgejo's database (SQLite for local Cove). To sync them between two instances without modifying Forgejo, we extract state as an **append-only event log** and use a git repo as the log's storage. Git is offline-first by design, handles distributed sync via push/pull, and is already part of the Cove toolchain.

### Data Model

For each repository, a sync repo contains:

```
sync.git/
├── issues/
│   ├── 001-forge-crash-on-large-repos/
│   │   ├── meta.json       # title, body, state, labels, assignees, etc.
│   │   ├── comments/
│   │   │   ├── 001-cristos-2026-06-13T09-42Z.json
│   │   │   ├── 002-cristos-macbook-2026-06-13T10-15Z.json
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
    └── remotes/network/main
```

Each issue and PR has:
- A `meta.json` (current state — derived by replaying the event log)
- A directory of immutable records (comments, reviews, etc.) — each is a file, never edited, only added
- An `events.log` — append-only stream of state changes

### Why Files Instead of Notes

Git notes tie metadata to commits. Issues and PRs aren't tied to commits — they're tied to branches (PRs) or independent of commits (issues). Files in a git tree are a more natural fit. Each comment is an immutable file; each state change is an event in a log. Append-only by construction.

### Sync Protocol

Both Cove instances have a sync daemon that watches for changes and exchanges events.

**Local → Network (push):**
1. Operator opens a PR on local Cove
2. Local sync daemon detects the new event (via Forgejo webhook or DB poll)
3. Daemon writes a new comment file and appends to the event log
4. Daemon commits to the local sync repo
5. Daemon pushes to network Cove's sync repo (via SSH or HTTPS)
6. Network sync daemon pulls, reads new events, applies them to its Forgejo database

**Network → Local (pull):**
1. Collaborator comments on a PR via network Cove
2. Network sync daemon detects the comment
3. Daemon writes the comment file and appends to its event log
4. Local sync daemon pulls from network (periodically, or on demand)
5. Daemon applies new events to its Forgejo database

Both directions use the same git-based protocol. The local and network repos are mirrors; events flow in both directions via push/pull.

### Conflict Resolution

Because each comment is an immutable file with a unique name (sequence + author + timestamp), two comments can never "conflict" — they're two distinct files. A merge of two sync repos is just a union of files. Git's three-way merge handles this cleanly.

The harder case is `meta.json` — multiple events changing the same field. Example: local changes the issue title at 10:00, network changes the same issue's title at 10:05. The last-writer-wins by event timestamp. If timestamps are too close to call, the operator is shown both versions and chooses.

For most fields (title, body, state, labels), the latest event wins. For additive fields (assignees, labels), the union wins. For comments, no conflict — each is a separate file.

### Offline-First

This is where the git-based approach shines. The operator can:
- Disconnect from the network
- Work on local Cove for days
- Open PRs, comment, change labels, close issues
- All events are committed to the local sync repo

When they come back online:
- Local sync daemon pushes the accumulated events to network
- Network applies them, exposes them to collaborators
- Collaborators who commented during the offline period have their comments waiting
- Local pulls, applies collaborator comments
- Both sides converge

No data loss. No merge conflicts on most fields. The operator's offline work is preserved and synced.

### Machine Identity in Events

Each event includes the originating instance and account:
```json
{
  "id": "evt-001-cristos-macbook-2026-06-13T10-15Z",
  "type": "comment.add",
  "issue": 42,
  "author": "cristos-macbook",
  "instance": "local-macbook",
  "timestamp": "2026-06-13T10:15:00Z",
  "body": "I can reproduce this on M2 MacBook Pro."
}
```

When the local sync daemon writes a comment from `cristos-macbook` and the network applies it, the author on network is `cristos-macbook` (or a bot account like `cristos-macbook[bot]`). This preserves provenance — everyone can see which machine authored which comment.

## What This Doesn't Solve

- **Real-time collaboration** — sync is eventual, not real-time. The operator sees their own comments instantly; collaborators' comments appear after the next pull cycle (default 60 seconds).
- **Conflict resolution for rapid simultaneous edits** — if the operator and a collaborator edit the same issue title within seconds of each other, last-writer-wins by timestamp. The "loser" sees a brief flash before the "winner" overwrites. Acceptable for solo dev + occasional collaborator.
- **Rich text / attachments** — comments can include images, attachments, mentions. All need to be encoded as files in the sync repo. The format handles this but adds complexity.
- **Forgejo-specific features** — reactions, project boards, milestones, labels with descriptions — all need explicit support in the event format. The format is extensible but each feature needs an event type.

## Why Not Forgejo Federation

Forgejo federation (ActivityPub/ForgeFed) is in progress. As of late 2025:
- **Stars federation** is built
- **User following** via ActivityPub has a merged PR passing end-to-end tests
- **PR/issue federation** is future work

The federation model assumes **one user, one home instance** — federation is for many operators across many instances. Our use case is **one operator, two home instances** — the same person with two primary forges. This isn't a supported federation pattern. The user model would fight us: each instance thinks its user is the canonical one.

Building atop federation would mean either:
- Waiting for upstream to add the pattern (multi-year, out of our control)
- Forking Forgejo to add it (significant maintenance burden)
- Implementing our own sync layer anyway (defeats the purpose)

Git-based event log sync sidesteps federation entirely. We don't need Forgejo to understand it — we just read/write the database via Forgejo's API and sync via our own protocol.

## Why Not Database Replication

SQLite (used by local Cove) supports some replication modes, but multi-master is not one of them. Replicating Forgejo's database directly would require:
- Single-writer (only one instance accepts writes at a time)
- Or conflict resolution at the database level (not Forgejo's domain)

Single-writer defeats the purpose: the collaborator can't comment if local is offline. Database-level conflict resolution is a much harder project than application-level event log sync.

## Implementation Path

1. **Define the event format** — JSON schema for issues, PRs, comments, reviews, labels, etc. Each event type has a clear shape.
2. **Build the local sync daemon** — watches Forgejo for changes, writes to the sync repo, commits. Small Python service, runs alongside Forgejo.
3. **Build the network sync daemon** — pulls from the local sync repo (or receives pushes), applies events to its Forgejo database. Same daemon, different config.
4. **Build the read path** — network's Forgejo reads from its own database. No changes to Forgejo needed. The sync daemon is a separate process.
5. **Handle initial sync** — when network Cove is first set up, bulk-export all issues/PRs from local, import to network. After that, incremental.
6. **Test offline convergence** — disconnect local, work for a day, reconnect, verify both sides converge. This is the core invariant.

## Open Questions

1. **Sync trigger cadence** — push on every event, or batch every N seconds? Trade-off: latency vs. resource use.
2. **Conflict UX** — when last-writer-wins isn't clear, how do we present the choice to the operator? Inline in Forgejo? A separate `cove sync` command?
3. **Schema evolution** — when Forgejo adds a new field, how does the event format evolve? Versioned events, optional fields, migration scripts?
4. **Attachments and large content** — images, PDFs, large comments. Store in the sync repo (bloats git) or use content-addressed storage (CAS) with git storing only the hash?
5. **Collaborator permissions on network** — who can comment? Just the operator, or invited friends? Network Cove is still a real Forgejo with real accounts.
6. **What if the operator wants the same account on both** — e.g., `cristos` exists on both local and network. Possible, but creates the collision problem. The machine-scoped account model avoids it.

## Next Steps

- Write a spec for the event format (SPEC: Multi-Stage Cove Sync Protocol)
- Prototype the sync daemon with a minimal event set (issues + comments)
- Test offline convergence with a simulated collaborator
- Decide on sync trigger cadence and conflict UX
- Plan migration path for existing local-only Cove users
