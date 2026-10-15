---
title: "DevIntern — summary"
type: commentary
source: devintern-snapshot.md
fetched: 2026-10-14
---

# DevIntern — summary

**Why selected:** The cleanest existing implementation of the *worker* pattern — a daemon that drains a backlog by handing ready tickets to your existing coding agents. Its semantics ("ready tickets become PRs", vague tickets get questions, incomplete attempts bounce back with an explanation) are the behavioral spec for cove's implementation layer.

**What it covers:**

- **Backlog scan:** polls the tracker with a configurable `task_query` ([defaults] in `workspace.toml`, poll_interval 60s) and runs the full pipeline per repo, one at a time. Incomplete attempts "bounce back to the tracker with an explanation instead of disappearing."
- **Agent harness-agnostic:** Claude Code, Codex, Cursor, **OpenCode** — one config line. "Your keys, your machines" — the harness runs locally with your API contract; code never hits their control plane.
- **Quality gates:** vague tickets → clarifying questions posted on the tracker instead of a wrong PR; agent self-reviews its diff (`--auto-review`) before humans look; review comments → addressed commits on the same branch; manual semantic conflict resolution, never force-pushing over human work.
- **Scheduled automations:** cron + prompt → the full ticket→PR pipeline (dependency upgrades, flaky-test triage). The prompt is the task — nothing needs to exist in the tracker.
- **Sentry integration:** recurring error groups → bugfix tasks → reviewed PRs.
- **Durability:** local SQLite queue across restarts, capped retries, rate-limit pausing, run-by-run dashboard at localhost:4400.
- **Trackers:** Jira, Linear, GitHub Issues, Trello, Asana, Azure DevOps, markdown files. **No Gitea/Forgejo** — the tracker side is the gap for cove.
- **License/commercial:** FSL-1.1-Apache-2.0 (converts to Apache-2.0 after 2 years per release); interactive CLI free forever; the unattended worker daemon is the paid product (Worker Pilot 14-day trial, $99 Supporter one-time or subscription).

**Cove relevance:** The tracker gap (no Forgejo) blocks direct use as-is, and the FSL + paid daemon make it a dependency with fine print for a personal offline platform. What to *borrow*: the `task_query`-driven drain loop, bounce-back-with-explanation semantics, and "vague → questions, not wrong PR" gate — these are exactly the behaviors a cove worker (bb-thread-based or ai-git-bot-based) should reproduce.