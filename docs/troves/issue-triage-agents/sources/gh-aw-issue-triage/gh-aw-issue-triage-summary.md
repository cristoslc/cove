---
title: "gh-aw AI issue triage — summary"
type: commentary
source: gh-aw-issue-triage-snapshot.md
fetched: 2026-10-14
---

# gh-aw AI issue triage — summary

**Why selected:** This is the state-of-the-art *pattern reference* for exactly the operator's ask, published by GitHub itself. It is GitHub-Actions-only (not Forgejo-runnable), but the workflow source is an open, copyable prompt + guardrail spec — the most valuable part is **what the triage pass decides**, especially the explicit "coding agent suitability" gate.

**What it covers:**

- **Event-driven + scheduled triage:** agent runs on `issues: [opened, reopened]`; the companion "Issue Monster" example shows the scheduled variant — every ~40 minutes, scan the open tracker, score candidates, hand the best to the coding agent ("triage-by-appetite", ensuring selected issues are "distinct and not overlapping").
- **The triage pass decides (verbatim structure):**
  1. Gather context (issue + comments, existing labels/types, search for duplicates, relevant docs)
  2. Completeness gate — insufficient info → `needs-info` label + focused questions, **do not guess**
  3. Spam/invalid gate — short-circuits the rest
  4. Classify: single issue type + priority (p0/p1/p2) with consistent definitions
  5. Duplicate vs related (apply `duplicate` only at high confidence, cite the number, never on title similarity alone; max 3 matches)
  6. **Coding-agent suitability: Suitable / Needs more info / Needs maintainer judgment** — "requirements and success criteria are clear, and the scope is self-contained" is the bar for Suitable
  7. One concise maintainer-facing report comment
- **Security shape:** the agent is read-only during analysis; all writes go through "safe outputs" (allowlisted labels, max counts, validated comment output) — prompt injection can't turn analysis into unrestricted writes.
- **Cost hygiene:** timeout-minutes budget, max-outputs caps, gh-aw audit showed a triage workflow running dozens of times daily should use a cheaper model.

**Cove relevance:** This is the **spec to copy** for any cove triage pass, whatever the runtime. The suitability gate + duplicate/related distinction + needs-info loop + safe-outputs write pattern are forge-agnostic ideas implementable as a Forgejo Actions cron workflow, a scheduled bb thread, or an ai-git-bot custom issue workflow. gh-aw itself compiles to GitHub Actions — not portable to Forgejo Actions.