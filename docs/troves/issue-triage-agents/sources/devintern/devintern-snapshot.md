---
title: "DevIntern README (verbatim)"
type: web
url: "https://github.com/getdevintern/devintern"
fetched: 2026-10-14
license: FSL-1.1-Apache-2.0
---

# DevIntern

**A worker for the coding agents you already have. Ready tickets become reviewed pull requests — on your machines.**

License: FSL-1.1-Apache-2.0 · npm `@getdevintern/code` · devintern.com

DevIntern is a self-hosted worker: it picks up ready tickets from the tracker you already use, runs Claude Code, Codex, Cursor, or OpenCode with your keys, and opens a self-reviewed pull request. You review diffs, not agent sessions. Interactive runs are free; the daemon is the paid product.

- **Your tracker:** Jira · Linear · GitHub Issues · Trello · Asana · Azure DevOps · plain markdown files
- **Your agent:** Claude Code · Codex · Cursor · OpenCode (one config line to switch)
- **Your keys, your machines** — billed on the contract you already have; code never hits our servers
- **Try it free** — run `devintern PROJ-123` from your terminal, no signup

## Quick start

```bash
# Requires Bun
curl -fsSL https://bun.sh/install | bash
bun install -g @getdevintern/code

# 1. Try one task in this repo (free, no signup)
devintern init
devintern ./tasks/my-task.md --create-pr   # or: devintern PROJ-123 --create-pr

# 2. Leave it running (free Worker Pilot or automation license)
devintern worker init
devintern worker
```

One local run proves the loop. The worker is the intern: it keeps picking up ready tickets and turns review comments on its pull requests into commits.

## Why teams use it

| | |
| --- | --- |
| **Worker** | One daemon. Ready tickets become pull requests. Review comments come back as commits on the same branch. |
| **Your stack** | Your tracker, your coding agent, your keys. DevIntern runs the tools you already use instead of selling you another agent. |
| **Quality gates** | Vague tickets get questions on the tracker instead of a wrong PR. The agent reviews its own diff before a human sees it. |
| **Self-hosted** | Runs on a laptop or VM you control. Your code and credentials stay there; the source is available under the FSL. |

## The worker

`devintern worker` is a long-running daemon that polls your tracker, implements ready tickets, opens pull requests, and keeps its own PRs healthy while your team writes specs, reviews code, or sleeps. Your code, credentials, and agent execution never leave your machine.

Once it's running, the worker:

- **Drains the backlog** — picks up every ticket matching your ready-tasks query (`task_query`) and runs the full pipeline per repo, one at a time; attempts that come up incomplete bounce back to the tracker with an explanation instead of disappearing.
- **Keeps up with review feedback** — watches the PRs it created; when someone requests changes or comments, the same pipeline addresses the feedback and pushes commits. No webhook plumbing needed in polling mode.
- **Resolves merge conflicts itself** — merges the base branch tip into a lagging PR branch and asks the agent to fix conflicts semantically, never force-pushing over human work.
- **Takes orders by @mention** — comment `@devintern address the review feedback` on *any* PR in the repo and it handles it (only users with push access can direct the bot).
- **Runs scheduled chores** — automations turn a cron schedule plus a prompt into the full ticket→PR pipeline, like dependency upgrades or flaky-test triage on Monday mornings. The prompt is the task: nothing needs to exist in your tracker.
- **Fixes production errors from Sentry** — the worker watches recurring error groups, turns valid ones into bugfix tasks, and ships the fix through the same pipeline as a reviewed pull request.
- **Survives reality** — accepted work persists to a local SQLite queue across restarts, retries are capped, and rate limits pause rather than break runs.
- **Shows its work** — every run is recorded stage-by-stage in a built-in dashboard at `http://localhost:4400`; routing rules and automations span a whole fleet of repositories from one `workspace.toml`.

## The worker, configured

```toml
[defaults]
task_query = "status=todo"
worker_task_args = "--create-pr"
poll_interval = 60

[[automations]]
id = "dependency-health"
enabled = true
interval = "6h"
prompt = """Pick one outdated dependency and upgrade it within the same major version."""
```

Sign in to evaluate unattended automation with a no-card Worker Pilot: 14 days with no task-count limit. Continued use requires the paid automation tier (one-time Supporter license or Team/Business subscription); interactive use stays free forever.

## Try one task

| Command | What you get |
| --- | --- |
| `devintern PROJ-123 --create-pr` | Ticket → feature branch → implemented diff → PR, with a summary posted back to the tracker |
| `devintern ./tasks/my-task.md --create-pr` | The same loop from a local markdown file — zero tracker credentials |
| `devintern --query 'status = "To Do"' --create-pr` | Batch mode: every ticket matching your JQL / Linear filter / GitHub search, run one after another |
| `devintern PROJ-123 --create-pr --auto-review` | The agent critiques its own PR diff and commits fixes before any human has to look |
| `devintern address-review <pr-url>` | Review comments on a pull request become addressed commits on its branch |
| `devintern resolve-conflicts <pr-url>` | The base branch is merged in and the agent resolves the conflicted files sensibly |
| `devintern doctor` | Pre-flight check for runtime, git, agent CLIs, tracker credentials — with a fix hint per problem |

When a ticket is too vague to implement responsibly, the agent posts clarifying questions back on the tracker instead of shipping a confidently wrong PR.

Delivery is a configurable pipeline. Add built-in verification or your own project-local TypeScript steps.

## Need a ticket first?

DevIntern PM (desktop, free) and `devpm` turn a prompt, error log, or Figma frame into a well-specified tracker ticket. They are optional intake for the worker.

## License and pricing

Source is under the Functional Source License, Version 1.1, with Apache 2.0 Future License (FSL-1.1-Apache-2.0). You can read it, audit it, self-build, and self-host. Each release converts to Apache-2.0 two years after publication.

- **Interactive use** → free forever
- **Worker Pilot** → 14 days with no task-count limit, no card required
- **Worker (unattended)** → Supporter ($99 once for one person's own repos) or a Team/Business subscription

The FSL grants no trademark rights: the DevIntern name and logo are trademarks of Daniil Pokrovsky (devintern.com) and may not be used to identify forks or derived products.

## Repository layout

- `@getdevintern/code` — the `devintern` CLI: ticket → agent → self-reviewed PR
- `@getdevintern/pm` — the `devpm` CLI: rough input → well-specified tickets
- `@devintern/pm-desktop` — desktop app for ticket drafting
- `packages/*` (shared) — agent harness, tracker clients, auth, license check, utilities

Website and control plane live elsewhere; this repo is the tool packages.