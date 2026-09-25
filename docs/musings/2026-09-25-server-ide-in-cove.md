# Muse: Server-Based IDE in Cove (and the "Code Editor" Exclusion)

**Date:** 2026-09-25
**Context:** Follows `docs/musings/2026-09-24-bb-harness-in-cove.md`, ADR-018 (ADE), ADR-019 (Activation Bundles)
**Status:** Half-formed. No PURPOSE.md change yet.

## The idea

Ship a server-based IDE as a Cove service, complementing the ADE. The harness orchestrates agents; the IDE gives the human a browser workbench on the same projects. One address (`ide.cove`), same `*.cove` TLS, same data dirs.

## Why the "code editor" exclusion may fall away

PURPOSE.md's "What Cove Is Not" currently narrows to **A code editor** (editors, LSPs, language runtimes stay out). But that exclusion was doing work the bundles concept now does better:

- The old exclusion was a proxy for "don't bloat the core with every dev tool." ADR-019 answers that directly with placement: dev tools belong to comfortable or advanced, not to the minimal harbor.
- Once the ADE was admitted (ADR-018), the identity question "does Cove ship code-touching tools?" was already answered yes. An IDE is the same category as the harness: a developer-experience service, harness-agnostic, placed by decision load.
- So the exclusion isn't a principle anymore; it's a placement decision. "Code editor" comes out of "What Cove Is Not" and becomes a bundle-membership question.

## Candidates, grounded

| Option | License / nature | Verdict |
|---|---|---|
| **code-server** (Coder) | MIT, browser VS Code fork | Strongest. Self-hostable, reverse-proxies cleanly. Known gaps: Remote Development extension set, Live Share, Copilot unavailable in browser. |
| **openvscode-server** (Gitpod) | MIT, upstream VS Code on a server | Comparable alt; same browser-access model. |
| **Microsoft VS Code Server** | Proprietary; license explicitly **forbids hosting as a service** | Reject as a Cove service. `code tunnel` is personal-use only. |
| **Cursor** | Proprietary; no self-hostable browser server (remote via SSH only) | Not a candidate. |

Tier 2 per ADR-016: MIT + real community = compound fork-safety; cost-to-graduate fine (free). Feature parity is the weak axis: browser forks lose the Microsoft-marketplace extensions and Remote Dev kit. Open VSX covers most of the rest but not all.

## Where it would land

- **Bundle placement (ADR-019):** a candidate for **advanced**, not comfortable. The decision-load test is the reason: an IDE drags in extension management, settings sync, and marketplace licensing choices. The ADE needed zero decisions; the IDE needs several. (Comfortable only if it ships with a locked-down default config and no extension surface.)
- **Hosting shape:** likely a container sharing the ADE machine's project checkouts, so the human edits what the agents edit, with no second copy. `ide.cove` via nginx, same pattern as `ade.cove`.
- **Extension source:** Open VSX vs Microsoft marketplace is a licensing decision, not a technical one. Microsoft's marketplace terms don't permit non-VS Code products (code-server historically ships Open VSX). Resolve before promising extension parity.

## Why it pairs well with the ADE

Agents and humans both act on projects; today the human's surface is the bb UI plus whatever local editor they run. A browser IDE closes the loop: watch an agent work in bb, open the same worktree in the IDE, fix or steer by hand, hand back. It is the visual complement to the harness, not a competitor.

## Open questions

1. code-server vs openvscode-server — pick by extension ecosystem and maintenance pace, not features (they converge).
2. Same container as the ADE machine, or its own service mounting the same projects? (Shared container is simpler; separate is cleaner per-project scoping.)
3. Does the IDE belong in ADR-019 as an advanced member, or is it its own ADR (like ADR-018 was for the harness)?
4. Auth: nginx basic auth, or something better for a browser IDE with WebSockets?
5. If adopted, PURPOSE.md's "code editor" bullet is deleted, and the bundle placement carries the guidance instead.

## Recommendation

Park it until ADR-019 lands. If bundles are accepted, this becomes a one-page ADR and a bundle-membership row, not a principle fight. The infra is trivial (a container, an nginx site); the only real decisions are bundle placement and extension licensing.
