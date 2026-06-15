---
title: "Multi-Stage .cove — git-bug + Forgejo"
created: 2026-06-13
revised: 2026-06-15
authored-by: deepseek-v4-flash:cloud, glm-5.1:cloud
status: Draft
---

# Multi-Stage .cove

## Hard Constraints

1. **PR/Issue sync is the whole point.** Without it, multi-stage is just "git push to a remote," which is trivial and solved. The hard part — keeping PRs, issues, and their comments in sync across instances — is the actual feature.
2. **Offline-first is immutable.** Local Coves must work fully without the always-online tier. Disconnected operation is the normal mode, not degraded mode.
3. **No public forge dependency.** No Codeberg, no GitHub, no shared external service. The operator owns all instances end-to-end.

## Use Cases

### 1. Phone Access

The operator wants to read and comment on issues and PRs from their phone. The phone is a **read-and-comment client**, not a development surface. It uses git-bug's web UI and Forgejo's web UI on tier-2 via HTTPS. The phone does not run a local Cove, does not run a sync daemon, does not store state.

### 2. Always-Online Tier-2 (Laptop Independence)

Laptops are not always online — they sleep, the lid closes, they go in a bag. Tier-2 is a **standby copy that's always reachable**. It can run on a Raspberry Pi, an old laptop, or a desktop that's always on. The operator checks their issues and PRs from their phone even when all laptops are asleep.

### 3. Multiple Local Nodes, One Project

The operator has multiple machines (MacBook, Linux desktop, home server) that may all work on the same project with different branches. Each machine runs git-bug CLI locally. All machines sync to the same tier-2.

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

### 4. PR-Sashaying: Nodes + Branches

Each machine creates branches with a per-node prefix. No collision at the git level — different branch names, different git refs. No collision at the PR level — different source branches, different PRs.

```
macbook/feature-x       # MacBook's work on feature-x
linux/feature-x         # Linux box's work on feature-x (same feature, different branch)
```

The sync layer doesn't rebase or merge. It mirrors git refs. The operator rebases on whichever machine they sit down at.

### 5. Offline-First Issue Work

The operator can:
- Shut down tier-2 (it's a standby, not a prerequisite)
- Disconnect MacBook from the network
- Work on MacBook for days: create issues, comment, change labels, close issues
- All via `git bug` CLI, stored locally in `refs/bugs/`
- When online again: `git bug push` syncs to tier-2, `git bug pull` gets other machines' changes

No data loss. No merge conflicts on issue data (git-bug uses event sourcing with Lamport clocks). The operator's offline work is preserved and synced.

## Identity Model

One account (`cristos`) on every surface. No mapping, no translation, no ghost users, no `[bot]` convention. git-bug has its own identity system (`refs/identities/`), but for a single operator, it's one identity everywhere.

**Lost: machine provenance.** We can't tell from an issue whether it was created on the MacBook or the Linux box. If provenance matters, the operator adds it to the comment body ("tested on M2 MacBook Pro").

## Architecture: git-bug + Forgejo

**Forgejo handles what it's good at:** git hosting, PRs (which are git operations — branches, diffs, merges), and CI. **git-bug handles what Forgejo can't sync offline:** issues, comments, labels. **Git handles distributed sync for both.**

git-bug is a distributed, offline-first issue tracker that stores issues as git objects under `refs/bugs/`. It syncs via regular `git push`/`git pull`. It has CLI, TUI, and web UI interfaces. It bridges to GitHub and GitLab (but not PRs). A Forgejo bridge is in progress (draft PR #1565).

### What git-bug Supports

| Feature | Core | CLI | TUI | WebUI |
|---------|:----:|:---:|:---:|:-----:|
| Issues | ✅ | ✅ | ✅ | ✅ |
| Comments | ✅ | ✅ | ✅ | ✅ |
| Labels | ✅ | ✅ | ✅ | ✅ |
| Title edits | ✅ | ✅ | ✅ | ✅ |
| Status (open/close) | ✅ | ✅ | ✅ | ✅ |
| Metadata | ✅ | ✅ | — | — |
| Pull requests | ❌ | ❌ | ❌ | ❌ |
| Milestones | ❌ | ❌ | ❌ | ❌ |
| Assignees | ❌ | ❌ | ❌ | ❌ |
| Threading | ❌ | ❌ | ❌ | ❌ |

### What Lives Where

| Concern | Lives In | Why |
|---------|----------|-----|
| Issue tracking (bugs, features, tasks) | git-bug | Offline-first, distributed, syncs via git |
| PR metadata (branch, diff, merge status) | Forgejo | PRs are git operations, belong in the forge |
| PR inline code review | Forgejo | Code review feature, not an issue feature |
| PR general discussion | git-bug | Issue-style discussion, belongs in the tracker |
| CI status | Forgejo | CI reports to Forgejo via webhooks |
| Labels | git-bug | Full label support |
| Milestones | git-bug (as labels for v1) | git-bug doesn't have milestones yet |

### What This Costs

- **Split UX.** Issues in git-bug's web UI, PRs in Forgejo's web UI. The operator switches between two interfaces.
- **Cross-references.** "closes #42" references git-bug IDs, not Forgejo issue numbers. A convention, not a technical problem.
- **git-bug maturity.** v0.10.1, pre-1.0. No milestones, no assignees, no PR support, no attachments in UI. The web UI is alpha.

### Why Not Alternatives

**Event log on git:** Over-engineered. Builds a distributed database on top of git. Five things to configure before it runs. Violates Cove's PURPOSE principle ("if it needs you to configure three things before it runs, it's not done").

**Single Forgejo instance + Tailscale:** Fails the airplane test. The laptop being offline is the normal mode.

**Forgejo forks:** Forks don't share issues. Every issue the operator creates on one fork is invisible on others. Degrades the sequential workflow.

**Database replication:** SQLite doesn't support multi-master. Single-writer defeats offline-first.

**CRDTs:** Complex to implement, don't integrate with Forgejo's SQLite, and still need a bridge. git-bug already provides the right abstraction.

**Email:** Primitive UX, no integration with Forgejo PRs.

## git-bug + Forgejo PR Integration

### Linking Issues and PRs

git-bug has no PR support. The integration bridges these two systems:

**PR → bug (Forgejo Action):** When a PR is opened in Forgejo, a Forgejo Action creates a corresponding git-bug issue with a `pr` label and `forgejo-pr-url` metadata. This is the v1 direction.

**Bug → PR (client-side notification):** When a bug is created with a `PR:` or `Sashay:` prefix and `forgejo-branch:` metadata, a client-side notification (curl after push) tells tier-2 to create a branch and PR. Forgejo Actions can't trigger on `refs/bugs/` pushes, so this direction uses a lightweight HTTP call instead.

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
      - name: Fetch bug refs
        run: |
          git config remote.origin.fetch '+refs/bugs/*:refs/remotes/origin/bugs/*'
          git config remote.origin.fetch '+refs/identities/*:refs/remotes/origin/identities/*'
          git fetch origin
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

### Bidirectional Events

| Forgejo Event | git-bug Action |
|---------------|----------------|
| PR opened | Create git-bug issue with title, body, `forgejo-pr-url` metadata, `pr` label |
| PR closed (not merged) | Close git-bug issue |
| PR merged | Close git-bug issue, add `merged` label |
| PR title updated | Update git-bug issue title |
| PR labels changed | Sync labels to git-bug issue |

| git-bug Event | Forgejo Action |
|---------------|----------------|
| Bug created with `PR:` or `Sashay:` prefix | Create branch (if needed) + create PR (`WIP:` for sashays) |

### Offline PR Creation

When the operator wants to start discussing a PR while offline:

1. Create a git-bug issue with a `pr` label: `git bug bug new -t "feature-x: refactor vault" -m "PR discussion for feature-x"`
2. Add `forgejo-branch: feature-x` metadata
3. When online, push: `git bug push; git push cove feature-x`
4. Client-side notification triggers branch/PR creation on tier-2

### Sashay Integration

The operator creates a bug titled `Sashay: refactor vault` with `forgejo-branch: refactor-vault` metadata. After pushing, tier-2 creates the branch from `main` and opens a WIP PR. The operator has a PR number immediately — no manual `fj pr create` step.

### Identity Mapping

Single operator: one identity (`cristos`) in git-bug, one account (`cristos`) in Forgejo. Trivial mapping by name/email.

## git-bug Web UI on Tier-2

The web UI (`git bug webui`) is a Go HTTP server with React+GraphQL frontend, embedded in the git-bug binary. Authentication is local-only (git config identity, no OAuth).

**Critical constraint: git-bug does not work with bare repositories** (Issue #178). Forgejo stores repos as bare repos. Running `git bug webui` inside Forgejo's bare repo fails.

**Solution: non-bare mirror clone on tier-2.**

```
Forgejo bare repo (/data/gitea/repositories/owner/project.git)
    │
    │  post-receive hook
    │  triggers: cd /opt/cove/project && git pull &&
    │    git fetch origin '+refs/bugs/*:refs/bugs/*' '+refs/identities/*:refs/identities/*'
    ▼
Non-bare clone (/opt/cove/project/)
    │
    │  git bug webui --host 0.0.0.0 --port 41935
    │  behind nginx: bugs.project.cove → 127.0.0.1:41935
    ▼
Phone browser: https://bugs.project.cove/
```

The non-bare clone stays in sync with Forgejo's bare repo via a post-receive hook. For multi-project Cove, each project needs its own clone and web UI process.

Local machines use `git bug` CLI — they don't need the web UI.

## Branching Comment Threads: Edge Case, Not Architecture Driver

Two machines writing comments offline that interleave misleadingly when merged is a real problem, but for a single operator it's an edge case. Single operator works on one machine at a time. NTP keeps clocks close. The operator wrote all the comments — they know the context.

git-bug uses Lamport clocks for ordering, which provides a deterministic total order regardless of concurrent edits. After sync, both machines agree on the order. It may not match wall-clock intent, but it's consistent and unambiguous.

**Mitigations:** do nothing (the operator understands the context), add a clarifying comment, rely on Lamport ordering, or edit/delete the confusing comments. None of these require a custom event log or replay engine.

## Happy Path Journeys

### J1: Laptop Online, At Home

```
Operator creates issue:  git bug bug new -t "Slow startup" -m "Takes 30s"
Operator pushes:          git push cove main && git bug push
Tier-2 updates:           post-receive hook → git pull + fetch bug refs
Phone sees it:            https://bugs.project.cove/ → issue appears
Operator creates PR:      fj pr create "Fix slow startup"
Action fires:             bug-sync creates git-bug issue with pr label
```

### J2: Laptop Offline — Airplane/Cabin Mode

```
Operator creates issue:  git bug bug new -t "Slow startup"
Operator adds comment:   git bug bug comment new <id> -m "Profiled: vault init"
Operator labels it:      git bug bug label new <id> performance
  (all stored locally in refs/bugs/, no network needed)

Operator goes back online:
Operator pushes:          git push cove main && git bug push
Tier-2 updates:           hook → git pull + fetch bug refs
Phone sees it:            all changes appear at once
```

### J3: Phone Only — Away From Desk

```
Phone opens:              https://bugs.project.cove/
Phone creates issue:      "Slow startup" via git-bug web UI on tier-2
Phone comments:           "Profiled: vault init" via web UI
Phone checks PRs:         https://git.cove/owner/project/pulls (Forgejo)

Operator returns to laptop, goes online:
Operator pulls:           git pull cove main && git bug pull
Laptop sees phone's issue: includes phone's comments
```

### J4: Phone Creates Issue, Laptop Pulls Later

```
Phone creates:            "Slow startup" on bugs.project.cove
  → written to tier-2's non-bare clone
  → cron pushes refs/bugs/* back to Forgejo
  → post-receive hook pulls into clone (idempotent)

Laptop comes online:
Laptop pulls:             git bug pull
Laptop sees issue:        includes phone's comments
Laptop responds:          git bug bug comment new <id> -m "Fixed"
Laptop pushes:            git bug push
Phone sees response:      refresh bugs.project.cove
```

### J5: Sashay — Bug → PR Automatically

```
Operator creates bug:     git bug bug new -t "Sashay: refactor vault"
  → adds forgejo-branch: refactor-vault metadata
Operator creates branch:  git checkout -b refactor-vault
Operator pushes:           git push cove refactor-vault && git bug push

Client-side notification triggers:
  1. Bug has "Sashay:" prefix
  2. Branch refactor-vault exists on Forgejo (just pushed)
  3. Creates WIP PR: "WIP: refactor vault"
  4. Links bug to PR via forgejo-pr-url metadata
```

### J6: PR Created Manually, Bug Created Automatically

```
Operator pushes branch:   git push cove feature-x
Operator creates PR:      fj pr create "Fix memory leak"

Forgejo Action fires (pull_request: opened):
  1. Fetches bug refs from origin
  2. Creates bug: "PR: Fix memory leak" with pr label
  3. Adds forgejo-pr-url metadata
  4. Pushes bug refs

Post-receive hook syncs bug refs to non-bare clone.
Phone sees:               new issue "PR: Fix memory leak" with pr label
```

### J7: Two Laptops, Both Offline, Then Both Sync

```
MacBook (offline):        git bug bug new -t "Slow startup"
MacBook (offline):        git bug bug comment new <id> -m "Reproduced on macOS"

Linux (offline):           git bug bug new -t "CI flaky"

MacBook goes online:       git bug push → pushes to tier-2
Linux goes online:         git bug pull → gets MacBook's issue
                          git bug push → pushes its issue

Lamport clocks ensure deterministic merge. No conflicts.
```

### J8: Phone Comments on PR, Laptop Reviews Later

```
Phone reviews PR #42:    Leaves inline comment on line 47 via Forgejo web UI
Phone approves:           "LGTM, just fix the typo"

Laptop goes online:
Laptop reviews PR:         fj pr view 42 — sees phone's comment
Laptop merges PR:          fj pr merge 42
Action fires:              closes linked git-bug issue, adds merged label
```

### J9: CI Updates Bug (Future)

```
Operator pushes code:      git push cove feature-x
CI fails:                   Tests fail on line 47
CI Action finds linked bug, adds ci-failing label and comment
Operator sees:              git bug bug show <id> — label ci-failing
```

### J10: Offline Bug, Online PR, Manual Linking

```
MacBook (offline):         git bug bug new -t "Fix memory leak" → bug #a1b2
MacBook goes online:        git push cove fix-memory-leak && git bug push
MacBook creates PR:        fj pr create "Fix memory leak"
Action creates:            bug "PR: Fix memory leak" → bug #c3d4 with pr label

Operator links them:        git bug bug label new a1b2 tracked-by-pr
```

### J11: Phone-Only, Reading and Commenting

```
Phone opens:               https://bugs.project.cove/ → browses issues
Phone comments on issue:    Adds comment via web UI
Phone reviews PRs:          https://git.cove/owner/project/pulls

Laptop wakes, goes online:  git pull cove main && git bug pull
Laptop sees phone's comment
```

### Summary of What Works Where

| Action | Laptop Online | Laptop Offline | Phone |
|--------|:---:|:---:|:---:|
| Create issue (git-bug) | ✅ | ✅ | ✅ (web UI) |
| Comment on issue (git-bug) | ✅ | ✅ | ✅ (web UI) |
| Close/label issue (git-bug) | ✅ | ✅ | ✅ (web UI) |
| View PRs (Forgejo) | ✅ | ❌ | ✅ (web UI) |
| Comment on PR (Forgejo) | ✅ | ❌ | ✅ (web UI) |
| Create PR (Forgejo) | ✅ | ❌ | ❌ |
| Create PR (sashay) | ✅ auto | ✅ bug offline | ❌ |
| Push code | ✅ | ✅ (queued) | ❌ |
| Merge PR (Forgejo) | ✅ | ❌ | ✅ (web UI) |
| CI status on bug | ✅ via Action | — | ✅ (web UI) |

## Gap Analysis: Journeys vs Architecture

### G1: Forgejo Actions Can't Trigger on refs/bugs/ Pushes

J5 (bug→PR) assumes a Forgejo Action fires when `refs/bugs/` are pushed. Actions only trigger on branch/tag pushes, `pull_request`, `issues`, `schedule`, and `workflow_dispatch`. Pushing `refs/bugs/` triggers nothing.

**Fix:** Client-side notification. After `git bug push`, a post-push hook or `cove` CLI command sends an HTTP request to tier-2 to check for bugs with `PR:`/`Sashay:` prefixes and create branches/PRs.

### G2: One-Way Sync (Bare → Clone Only)

The post-receive hook syncs Forgejo's bare repo → non-bare clone. But the web UI writes to the clone (J3, J4 — phone creates issues). Those writes never reach Forgejo, so laptops pulling from Forgejo never see phone-created issues.

**Fix:** A cron on tier-2 that pushes `refs/bugs/*` and `refs/identities/*` from the clone back to Forgejo every 30 seconds. The post-receive hook then pulls them back (idempotent loop).

### G3: Actions Checkout Doesn't Include Bug Refs

`actions/checkout@v4` only fetches the tested branch. `refs/bugs/` won't be in the checkout. `git bug bug new` operates on an empty bug database.

**Fix:** Explicit fetch in the Action:
```yaml
- name: Fetch bug refs
  run: |
    git config remote.origin.fetch '+refs/bugs/*:refs/remotes/origin/bugs/*'
    git config remote.origin.fetch '+refs/identities/*:refs/remotes/origin/identities/*'
    git fetch origin
```

### G4: Post-Receive Hook Doesn't Pull Bug Refs

`git pull` only pulls the tracked branch. Bug refs are under `refs/bugs/`, not `refs/heads/`.

**Fix:** The hook must also fetch bug refs explicitly:
```bash
cd /opt/cove/project
git pull
git fetch origin '+refs/bugs/*:refs/bugs/*' '+refs/identities/*:refs/identities/*'
```

| Gap | Journey Broken | Fix |
|-----|----------------|-----|
| G1: Actions can't trigger on refs/bugs/ | J5 (bug→PR) | Client-side notification after push |
| G2: One-way sync (bare→clone only) | J3, J4 (phone writes) | Cron pushes clone→Forgejo every 30s |
| G3: Actions missing bug refs | J6 (PR→bug) | Fetch refs/bugs/* and refs/identities/* in Action |
| G4: Post-receive hook doesn't pull bugs | All journeys | Hook must fetch bug refs, not just git pull |

## Implementation Path

1. **Evaluate git-bug** — install on MacBook, test CLI, TUI, web UI. Verify offline workflow.
2. **Set up git-bug on tier-2** — non-bare mirror clone, post-receive hook with bug ref fetching (G4), `git bug webui` behind nginx.
3. **Set up bidirectional sync** — cron pushes clone→Forgejo every 30s (G2). Post-receive hook pulls back (idempotent).
4. **Set up git-bug on each local machine** — `git bug` CLI. Issues stored in `refs/bugs/` alongside code.
5. **Configure sync** — `git bug push` / `git bug pull`. Bug refs pushed/pulled alongside code.
6. **Write Forgejo Action for PR→bug** — `bug-sync.yaml` with explicit bug ref fetching (G3).
7. **Write client-side notification for bug→PR** — post-push hook or CLI command notifies tier-2 (G1).
8. **Test offline convergence** — create issues on MacBook, push, view on phone.
9. **Test bidirectional sync** — create issue on phone, verify it reaches Forgejo and laptop.
10. **Test hub-and-spoke** — MacBook and Linux both sync to tier-2.
11. **Test PR→bug linking** — create a PR, verify Action creates corresponding bug.
12. **Test bug→PR linking** — create Sashay bug, push, verify branch and WIP PR created.

## Open Questions

1. **Same repo or separate repo?** — git-bug stores issues in `refs/bugs/` within the code repo. Same repo means issues travel with code. Evaluate whether this is the right UX.
2. **PR ↔ issue linking** — Forgejo Action for PR→bug (v1). Client-side notification for bug→PR. Inline code review stays in Forgejo.
3. **Bug → PR inverse** — Client-side notification after push. Branch creation via Forgejo API if branch doesn't exist. Sashay prefix creates WIP PR automatically.
4. **Phone workflow** — git-bug web UI on tier-2 supports full CRUD. Phone can create and comment. Needs write access to non-bare clone.
5. **Bare repo constraint** — git-bug doesn't work with bare repos (Issue #178). Non-bare mirror clone + post-receive hook + bidirectional sync cron.
6. **Multi-project scaling** — Each project needs its own clone and web UI process. Reverse proxy routes by project.
7. **Migration path** — git-bug Forgejo bridge (PR #1565, import-only) can migrate existing Forgejo issues.
8. **CI status on issues** — Future: Action adds `ci-failing`/`ci-passing` labels to linked bugs. Skip for v1.
9. **git-bug maturity** — v0.10.1, pre-1.0. No milestones, assignees, PRs, attachments in UI. Web UI is alpha. Evaluate for v1 acceptability.
10. **Forgejo Action prerequisites** — Action needs git-bug installed on runner and bug refs fetched before commands.

## Next Steps

- Install git-bug on MacBook and test full workflow (create, comment, close, push, pull, web UI)
- Evaluate git-bug web UI on a phone browser
- Decide: same repo or separate repo for bug data
- Design post-receive hook for bare repo → non-bare clone sync (with bug ref fetching)
- Design bidirectional sync cron (clone → Forgejo)
- If git-bug passes evaluation, write a SPEC for the integration architecture