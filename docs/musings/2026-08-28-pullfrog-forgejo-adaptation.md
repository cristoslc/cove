---
title: "Pullfrog → Forgejo: what actually ports, what doesn't"
created: 2026-08-28
revised: 2026-08-28
status: Draft
---

# Pullfrog → Forgejo: what actually ports, what doesn't

Follow-up to the earlier "pullfrog as forge steward" sketch. That one was
speculative. This one is grounded in actually reading pullfrog's code and
probing the running Forgejo at `git.cove`.

The headline: the `gh`-CLI-as-MCP-tool layer ports with caveats. The deeper
layers do not port for free — and one of them is a hard conflict with Cove's
offline-first charter. "Adapt it for Forgejo" is a real project, not a config
flip.

## What I actually probed

- `git.cove` is Forgejo **15.0.3+gitea-1.22.0**. Swagger at `/api/swagger`,
  spec at `/swagger.v1.json`. Base path `/api/v1`. **REST only** — no GraphQL
  endpoint anywhere in the spec. (Forgejo/Gitea never shipped GraphQL.)
- Pullfrog's source is in `~/Documents/code/pullfrog-fork`. I read
  `mcp/gh.ts`, `utils/apiCommit.ts`, `utils/roleMirror.ts`, `utils/token.ts`,
  `utils/apiFetch.ts`, `utils/apiUrl.ts`, `utils/github.ts`, and grepped every
  `api.github.com` reference.

## Layer 1 — the `gh` MCP tool (ports, with one caveat)

`mcp/gh.ts` is a generic argv passthrough to the `gh` CLI with **no subcommand
allowlist**. It just shells out `gh <args>` with `GH_TOKEN`, `GH_CONFIG_DIR`,
isolated from any host `~/.config/gh`. So "does Forgejo work with `gh`
natively?" → yes, the same way any GitHub-API-compatible host does: point
`gh` at it (`GH_HOST` / `gh auth login --hostname git.cove`), hand it a
Forgejo PAT as `GH_TOKEN`, and the REST-shaped subcommands (`pr list`, `issue
view`, `api repos/...`) work.

The caveat is right in the tool's own description string: *"`gh api graphql`
is available."* On Forgejo it isn't. There is no `/graphql`. The agent is told
GraphQL is on the table, and the moment it reaches for it — `gh api graphql
-f query=...` — it gets a 404. That's not catastrophic (the agent can fall
back to REST), but it's a contract the tool advertises that the backend
can't honor. Fix is cheap: gate that sentence on a flag that's false for
Forgejo deployments. But it's a real, if small, edit — not zero-work.

## Layer 2 — signed commits (`apiCommit.ts`) — does NOT port cleanly

`utils/apiCommit.ts` hardcodes `GITHUB_API = "https://api.github.com"` and
talks the GitHub git-database REST API (blob → tree → commit → ref) with
`X-GitHub-Api-Version: 2022-11-28`. This is the `commit_changes` /
`push_branch` path in "signed-commits" mode. The whole point of that path is
that commits created with an installation token and no custom author are
**signed server-side by GitHub** and show as Verified — that's how it
satisfies "require signed commits" branch protection.

Two problems for Forgejo:

1. The base URL is a `const`, not env-driven. `token.ts` *does* respect
   `GITHUB_API_URL` (the GHES escape hatch), but `apiCommit.ts` does not —
   it's pinned to `api.github.com`. So even pointing it at a GHES-style
   compatible host requires an edit.
2. Bigger: the **Verified badge is GitHub's server-side signing**. Forgejo
   doesn't replicate it. Forgejo can absolutely accept commits via its REST
   git-database API, but they land as ordinary commits — no green "Verified"
   stamp. If branch protection on the Cove Forgejo is set to "require signed
   commits," the agent's API-commits won't satisfy it. The signing guarantee
   that justifies the whole `apiCommit.ts` existence disappears.

So this layer needs a real decision, not a re-point: either drop
signed-commits mode for Forgejo (and accept that agent commits look like
anyone else's), or wire Forgejo's own signing story (SSH/gpg signing keys on
the runner, or Forgejo's WIP commit signing) into the path. Either is
engineering, not configuration.

## Layer 3 — the ephemeral token model — does NOT port, architecturally

`roleMirror.ts` + `utils/token.ts` + `utils/github.ts` + `gitAuthServer.ts`
are built on **GitHub App installation tokens minted per run via OIDC**,
scoped to exactly one repo, revoked at run end. The invariant — "a leaked run
token must never grant more than the triggering user already has, and dies
at run end" — is *constructed* from properties that GitHub App tokens have
and Forgejo tokens don't:

- `gitAuthServer.ts` hits `https://api.github.com/installation/token`.
  Forgejo has no GitHub-App-installation-token OIDC flow. There's nothing to
  mint.
- `roleMirror.ts` derives a permission subset from the triggerer's effective
  role and hands it to `gh`. The "subset" semantics (e.g. `contents` is never
  `write`, so `gh pr merge` is structurally impossible) are enforced by what
  scopes you ask for when minting the installation token. Forgejo PATs and
  scoped tokens don't have that same per-run-mint-then-revoke lifecycle.
- `token.ts` revokes the installation token in a single-flight cleanup
  handler. There's no equivalent "revoke this run's token" call against
  Forgejo without per-run token creation, which Forgejo doesn't really do.

Adapting to Forgejo means a **long-lived PAT** (or Forgejo's newer
fine-grained scoped tokens). That breaks the leak-survivability invariant
the entire `gh` tool comment block is written around. A leaked long-lived
PAT is not survivable the way a per-run installation token is. You'd want
either (a) Forgejo scoped tokens rotated by a Cove-side helper per run, or
(b) accept the weaker guarantee and document why it's acceptable for a
single-operator, localhost-only forge. (b) is probably fine for Cove's
threat model — there's no multi-tenant leakage to worry about — but it's a
conscious downgrade, not a free carry.

## Layer 4 — the object-scoped MCP tools (corrected: two camps, not one)

> **Correction (2026-08-28).** The first version of this musing claimed the
> object-scoped tools "route through `pullfrog.com`'s hosted backend." That
> was wrong for the majority of them. Re-reading the code: the tools split
> into two camps — most go **Octokit-direct to GitHub REST**, only a few go
> through the proprietary backend.

The object-scoped MCP tools are **not** a monolith. They split:

### 4a — Octokit-direct (the majority): adaptable to Forgejo

`create_issue_comment`, `create_pull_request_review`, the `pr`/`issue`/
`labels` operations all call `ctx.octokit.rest.*`. Octokit is constructed in
`utils/github.ts:589` with **no `baseUrl` set** — so it defaults to
`https://api.github.com`, but `baseUrl` *is* a supported option. Pointing it
at Forgejo's `/api/v1` is a one-line config change. The real work is that
Forgejo is **Gitea-API**, not GitHub-API: Octokit's `.rest.*` methods are
generated from GitHub's OpenAPI spec, so the endpoint *paths* and *response
shapes* overlap heavily with Gitea's REST API but are **not identical**
(field names differ, some paths differ, pagination headers differ). That's
endpoint-mapping work, not backend reimplementation.

In these files `getApiUrl()` / `pullfrog.com` is only used to build dashboard
*links* ("Implement plan ➔"), not to make the API call itself. Strip the
links and the tool still functions against the forge directly.

### 4b — backend-dependent (the minority): not self-hostable from this repo

A handful of features genuinely route through `apiFetch` → `pullfrog.com`:

- `similarIssues` → `/api/repo/.../issues/n/similar` — needs a server-side
  embedding index for semantic issue retrieval.
- `selectMode` plan-comment → `/api/repo/.../issue/n/plan-comment`.
- `upload` → artifact upload to the backend.
- the `${API_URL}/trigger/...` dashboard trigger links.

The `pullfrog.com` backend (dashboard, managed GitHub App, OAuth, billing,
OIDC token minting, the embedding index) is **not in this repo**. It is a
proprietary hosted service. You cannot stand it up from this fork.

For a single-operator offline Cove, most of 4b is droppable — the dashboard,
billing, managed-App, and OAuth glue solve multi-tenant SaaS problems Cove
doesn't have. The only one with real value is `similarIssues` (semantic
duplicate detection), which would need a local embedding index to
reimplement.

## Is pullfrog self-hostable?

**Partially, and where it counts for Cove, yes.** The action + CLI + MCP
server (this repo) are open source and run inside *your own* runner (GHA or
Forgejo Actions). The proprietary `pullfrog.com` backend is not in this fork
and is needed only for the 4b features above. The bulk of the object-scoped
layer (4a) is Octokit-direct and therefore adaptable to Forgejo.

## So: viable, with the cost concentrated in API mapping, not backend reimpl

| Layer | Ports to Forgejo? | Cost |
|---|---|---|
| `gh` MCP tool (generic CLI passthrough) | yes, with GraphQL caveat | small — gate the "graphql available" string, configure `GH_HOST` |
| Signed commits (`apiCommit.ts`) | no cleanly | medium — drop Verified guarantee or wire Forgejo signing |
| Ephemeral token model (`roleMirror`/`token`/`gitAuthServer`) | no architecturally | medium — long-lived PAT + accept weaker leak guarantee (fine for Cove's model) |
| Object-scoped tools — Octokit-direct (4a: comment/review/pr/issue/labels) | yes — set Octokit `baseUrl`; map Gitea-vs-GitHub API diffs | **medium — this is the real work now, and it's endpoint mapping, not a backend rewrite** |
| Object-scoped tools — backend-dependent (4b: similarIssues/plan-comment/upload/dashboard) | no from this repo | drop for Cove, or reimplement `similarIssues` with a local index |

The earlier framing ("no new interface required, just configure `gh`") was
wrong in the *opposite* direction from the first correction. The truth: the
`gh`-CLI layer ports trivially; the Octokit-direct object-scoped layer ports
with real API-mapping work (Gitea ≠ GitHub, but close); only a small backend-
dependent tail is not self-hostable, and most of that tail is SaaS glue a
single-operator Cove drops anyway.

## Does a fully self-hosted version of pullfrog exist?

No — not upstream. CONTRIBUTING.md says it outright: *"This repo
(`pullfrog/pullfrog`) is the open-source GitHub Action that powers Pullfrog.
The rest of the product (web app, API) is proprietary and lives elsewhere."*
The `pullfrog.com` backend (dashboard, managed GitHub App, OAuth, billing,
OIDC token minting, the similar-issues embedding index) is not in this fork
and has no self-hostable release. Every "self-hosted" reference in the repo
is about GitHub Actions *runners*, not self-hosting the pullfrog service.

So the question becomes: is there a **different** project that does what
pullfrog does (bring a coding agent into the forge for PR review / issue
triage) but is fully self-hostable and Forgejo-compatible? Yes.

## The fully self-hostable alternative: PR-Agent

`The-PR-Agent/pr-agent` — MIT, ~12.8k★, recently donated by Qodo to a
community-owned org (now being transferred to an open-source foundation).

Why it fits Cove where pullfrog doesn't:

- **Fully self-hostable, no proprietary backend.** A single Docker service +
  webhooks. No `pullfrog.com`-equivalent. Nothing to rugpull.
- **Explicit Gitea support.** The feature matrix lists Gitea ✅ for Describe,
  Review, Improve, CLI, App/webhook, Agent skills (`SKILL.md`), and
  `AGENTS.md` context files. Forgejo is a Gitea fork with a compatible REST
  API → Gitea support = Forgejo support, modulo testing.
- **LLM-agnostic.** Any OpenAI-compatible endpoint → point it at
  `https://litellm.cove.local/v1`. Reuses the LiteLLM service Cove already
  runs. Offline as long as the LLM provider is (Ollama via the proxy, etc.).
- **Aligns with existing agent infra.** Reads `AGENTS.md` and `SKILL.md` —
  the same conventions the operator's harnesses already use.

What it gives up vs pullfrog:

- **Fixed tools, not open-ended.** PR-Agent ships `/describe`, `/review`,
  `/improve`, `/ask` — a closed toolset, not the "tag the bot and it does
  anything" model. No `@pullfrog`-style arbitrary-prompt runs, no
  auto-fix-on-CI-failure loop, no issue→PR generation.
- **Some features are GitHub-only.** `Ask on code lines`, `Update CHANGELOG`,
  Actions-runner mode, and the tagging bot are blank in the Gitea column.
  Core review/describe/improve work on Gitea; the edges don't.
- **No MCP server.** Pullfrog's MCP server *exposes tools to* a coding agent
  (agent drives the forge). PR-Agent *is* the agent with fixed tools.
  Different integration model — PR-Agent won't make OpenCode/Claude forge-
  aware the way pullfrog's MCP tools do.

## Other self-hostable candidates considered

- **OpenHands** (`OpenHands/OpenHands`, MIT, ~86k★) — self-hostable "developer
  control center for coding agents," but GitHub-centric (no Gitea/Forgejo in
  the README; integrates Slack/GitHub/Datadog). Heavier than a forge bot and
  the wrong shape for Cove.
- **Aider** (`Aider-AI/aider`, Apache-2.0, ~49k★) — terminal pair
  programmer, not a forge-integrated bot. Different category; complements
  rather than replaces.

## Recommendation shift

The pullfrog adaptation is viable but costs API-mapping work (Gitea ≠
GitHub) plus dropping the proprietary-backend tail — and what you get is an
open-ended agent that still leans on GitHub-App-shaped assumptions (ephemeral
tokens, signed commits) that don't map to Forgejo. **PR-Agent is the cheaper
path to a Cove forge steward**: it already speaks Gitea, already self-hosts
as one container, already targets an OpenAI-compatible endpoint, and needs
no proprietary backend. The trade is capability breadth (fixed review tools
vs open-ended agent runs).

The decision to actually sit with: does Cove want a **focused PR review bot**
(PR-Agent, fits today, less magic) or an **open-ended forge-aware agent**
(pullfrog adapted, more magic, more work, more GitHub-shaped assumptions to
shed)? That's a parley, not a binary — and PR-Agent may be the v1 while a
pullfrog-style MCP layer is the v2 if the focused tools turn out to feel
narrow.

## Open question to sit with

The honest question isn't "can we adapt pullfrog for Forgejo" (yes, at the
cost above). It's whether the object-scoped tool layer is worth adapting
against Forgejo's REST API, or whether the `gh`-CLI tool alone — agent drives
`gh pr`, `gh issue`, `gh api` directly — is enough for a single-operator forge
where there's no multi-user permission mirror to enforce anyway. The
`roleMirror` machinery exists to constrain a *multi-user* GitHub App; in a
single-operator Cove, the operator's PAT *is* the right scope, and the
object-scoped layer may be solving a problem Cove doesn't have. Worth a
parley before committing to the API-mapping work.