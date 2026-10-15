---
title: "forgejo-mcp — summary"
type: commentary
source: forgejo-mcp-snapshot.md
fetched: 2026-10-14
---

# forgejo-mcp — summary

**Why selected:** The missing tool layer for the compositional path — a purpose-built MCP server (Go, MPL-2.0, Docker image `ronmi/forgejo-mcp`) that exposes Forgejo/Gitea issue and repo management to *any* MCP-speaking agent harness. Forgejo is named first-class here, not inferred from Gitea compatibility.

**What it covers:**

- **Issue management tools:** create/edit/view issues, add/remove/replace labels, comments, dependencies, and **issue blocking** (one issue blocks another — a triage-grade primitive for "won't do until X lands").
- **Organization:** labels, milestones, repo search/listing; PRs (view), wiki, releases, Forgejo/Gitea Actions tasks viewable.
- **Headless-friendly deployment:** stdio mode for local harnesses (docker or binary) — the natural fit for bb/OpenCode threads; also SSE/HTTP mode (single- or multi-user token auth) on `:8080` for a central cove gateway.
- **Its pitch already names the triage use cases:** "Automated issue categorization: automatically tag issue labels and set milestones based on content; Priority sorting: let AI analyze issue content to help prioritize tasks."
- **Security guidance:** env-var tokens, minimal scopes, regular rotation.
- Small project (~56–60 stars) — small community, but the surface is thin over a stable REST API.

**Cove relevance:** With `--server https://git.cove.local --token <scoped-pat>` in stdio mode, any bb OpenCode thread gets the full issue-management tool surface — so a scheduled "scan and triage the backlog" bb thread (cron via bb automations, or overnight autonomy flow) can be the triage brain with zero new build work. This is the lightest fully-offline path: Forgejo (already running) + forgejo-mcp (single container) + an agent harness bb already runs.