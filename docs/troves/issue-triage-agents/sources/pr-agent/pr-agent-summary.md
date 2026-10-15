---
title: "PR-Agent — summary"
type: commentary
source: pr-agent-snapshot.md
fetched: 2026-10-14
---

# PR-Agent — summary

**Why selected:** Already named as the fallback in the Decided pullfrog musing (fixed-tools instead of open-ended agent). Re-verified here from the current repo for its *triage-relevant* surface, which the musing did not evaluate: the issue-scoped `similar_issue` tool.

**What it covers:**

- **`/similar_issue`** — issue-scoped tool: "find similar issues in the repository". Runs from a comment or `pr-agent --issue_url <ISSUE_URL> similar_issue`. This is duplicate detection / related-work linking — a reusable triage sub-task, and the only *shipped* implementation of the semantic-issue-matching feature the pullfrog musing dropped as `similarIssues` (4b) and sketched reimplementing "with a local embedding index."
- **Git providers:** GitHub, GitLab, Bitbucket, Azure DevOps, **Gitea** ✅ (Forgejo untested, Gitea API compatible). Per the supported-platforms docs, some features degrade on Gitea (Generate Labels output posts as a comment where the provider can't set labels).
- **Models:** anything reachable through **LiteLLM** — explicitly including Ollama. Fits cove's `litellm.cove.local/v1` proxy without change.
- **Deployment:** CLI, Docker, webhooks, self-hosted. Single-LLM-call per tool (~30s, cheap) — well suited to a bulk back-log pass.
- **Status:** community-owned legacy project; Qodo donated it to an open-source foundation; Docker namespace migrated to `pragent/pr-agent`.
- Limitations unchanged: fixed tools, no issue→PR implementation, no scheduled scanning, Gitea-only feature gaps at the edges.

**Cove relevance:** Not the triage brain itself, but a candidate *component*: `similar_issue` as a cheap duplicate-detection pass over the Forgejo issue backlog, callable from CLI inside any Forgejo Actions workflow or bb thread. A single-operator deployment should run it headless per issue rather than as a comment bot.