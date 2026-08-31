---
title: "Pullfrog → Forgejo: what actually ports, what doesn't"
created: 2026-08-28
revised: 2026-08-28 (three times — corrected layer-4; harness-agnostic
constraint flips recommendation back to pullfrog; security re-accounting +
fail-closed config gate + forge-layer synthesis)
status: Decided
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

## What the user actually wants: the CodeRabbit/Pullfrog category

Refined the target after the PR-Agent detour. The category is specifically:
**an always-on, forge-integrated bot that auto-reviews PRs on open, responds
to `@mention` with open-ended agent runs, and is fully self-hostable.**
PR-Agent is fixed-tools (`/describe` `/review` `/improve` `/ask`), not
open-ended — so it's adjacent, not in-category. OpenHands was the candidate
question; it's the **wrong shape**: a general "developer control center for
coding agents" (Agent Canvas UI, agent backends in Docker/VMs, automations
that decompose GitHub issues into tasks on schedule/webhook). Heavyweight,
GitHub+Slack+Linear-centric, no Gitea/Forgejo, and its automation model is
"scheduled/event-driven task decomposition," not "always-on PR review bot
that responds to `@mention`." Overkill and not purpose-built as a forge bot.

## The answer: `vercel-labs/openreview`

A near-direct CodeRabbit/Pullfrog clone that is fully self-hostable (~1.6k★,
Vercel Labs).

- **Mention-triggered, open-ended.** `@openreview` in a PR comment (optionally
  with specific instructions) → a Claude agent reviews the diff, explores the
  codebase, runs project tooling, posts inline suggestions. The
  CodeRabbit/Pullfrog model, not fixed tools.
- **Fully self-hostable.** A single Next.js app (webhook handler + agent).
  Default deploy is Vercel, but it's just a Next.js app — runs in a Cove
  container. No proprietary backend (the thing pullfrog has and won't release).
- **Uses `.agents/skills/SKILL.md`.** Ships with built-in review skills and
  loads custom skills from `.agents/skills/` at runtime — the *same* skill
  convention the operator's harness already uses. Native alignment.
- **GitHub-only today** — but the GitHub coupling is **concentrated in ~5
  files**, and the agent core is forge-agnostic:

  ```
  lib/agent.ts      ← agent core (forge-agnostic)
  lib/skills.ts     ← .agents/skills loader (forge-agnostic)
  lib/tools/        ← agent tools (forge-agnostic)
  lib/github.ts     ← GitHub API layer  ← swap to Gitea/Forgejo REST
  lib/bot.ts        ← comment posting   ← retarget
  app/api/webhooks/ ← webhook handler   ← accept Forgejo webhook payload
  workflow/steps/get-github-token.ts, check-push-access.ts  ← retarget
  ```

  Extending to Forgejo is a **contained** project: rewrite `github.ts`
  (octokit `baseUrl` → `/api/v1`, or swap to a Gitea client), swap the webhook
  handler to consume Forgejo webhook payloads, adjust two workflow steps.
  Agent core, skills, tools don't change. Categorically smaller than the
  pullfrog adaptation — no proprietary backend to replace, no ephemeral
  GitHub-App token model to shed, no signed-commits Verified guarantee to
  lose. The operator already said they're fine extending a GitHub-only thing
  to Gitea/Forgejo, and this is the cleanest such extension surface found.

## Runner-up: `mattzcarey/shippie`

MIT, ~2.5k★, "extendable code-review agent." Mention-triggered
(`/shippie review`), provider-agnostic (Anthropic/OpenAI/OpenRouter/CF Workers
AI), supports `MCP_SERVERS`, `AGENTS.md`/`CLAUDE.md` injection, Agent Skills,
subagent delegation, and runs on GitHub Actions **or GitLab CI** (already
multi-forge-ish). Slightly less open-ended than openreview and more
review-focused, but it already has a foot in non-GitHub CI — worth keeping in
view as the fallback if openreview's Claude-only coupling turns out to be a
constraint.

## New hard constraint: must run any agent harness (not Claude-only)

The operator's requirement tightened: the forge steward must be able to
drive **any agent harness** (Claude Code, OpenCode, Codex, Aider, …), not
bake in one vendor's SDK. This is the constraint that flips the recommendation
back. Re-verified both candidates against it:

- **openreview is Claude-only.** `lib/agent.ts` is a bespoke agent loop on
  `@workflow/ai/agent` (Vercel Chat SDK → Claude), with its own tools
  (`lib/tools/bash.ts`, `read-file`, `write-file`, `reply`, `load-skill`).
  It does **not** spawn an external harness — it *is* the harness, and the
  harness is Claude-shaped. Making it harness-agnostic means ripping out the
  `DurableAgent` core and replacing it with a harness-spawning abstraction
  (subprocess + MCP bridge for tools). That is a **rewrite of the agent core**,
  not the "~5-file retarget" the prior version of this musing claimed. That
  retarget estimate was valid only under the assumption the Claude core stayed.
  Under the harness-agnostic constraint, openview is the wrong base.
- **shippie is single-harness.** Its "provider-agnostic" claim is
  *model*-agnosticism (Anthropic/OpenAI/OpenRouter/CF Workers AI), not
  *harness*-agnosticism. It runs its own flue-based agent loop. Same failure
  mode as openreview under this constraint.

## Why pullfrog is back as the right base

Pullfrog's `agents/` directory is a clean harness-agnostic abstraction that
precisely satisfies the new constraint:

```ts
// agents/index.ts
import { claude } from "./claude.ts";
import { codex } from "./codex.ts";
import { opencode } from "./opencode.ts";
import type { Agent } from "./shared.ts";
export const agents = { claude, codex, opencode } satisfies Record<string, Agent>;
```

- Each harness (`claude.ts`, `codex.ts`, `opencode.ts`) is a driver that
  **spawns the harness as a subprocess** and feeds it the MCP tool server.
  The harness keeps its native file-editing, bash, reasoning — pullfrog
  doesn't reimplement the agent, it *hosts* whichever one you point it at.
- Selection is `PULLFROG_AGENT` env var with auto-select fallback
  (`utils/agent.ts:152`). Adding a harness = one new file implementing the
  `Agent` interface. **opencode is already first-class** (`agents/opencode.ts`,
  `opencodePlugin.ts`) — the operator's harness is supported today. Adding
  `pi` would be one more driver file.
- The MCP tool server (the forge-API layer, layers 1 + 4a) is what gets
  bridged to whichever harness is spawned. That's the harness-agnostic
  contract: tools are exposed *to* the harness, the harness is swappable.

This is the one constraint openreview and shippie can't meet without a
rewrite, and pullfrog meets it for free. So the proprietary-backend caveat
from the earlier analysis is real but **narrower than it first looked** under
this constraint: the backend is needed for the managed-GitHub-App OAuth flow,
billing, `similarIssues`, `plan-comment`, the dashboard, and OIDC token
minting — *none of which the core harness-agnostic forge-bot loop needs*.
A single-operator Cove replaces the GitHub-App flow with a Forgejo PAT
(fine — the `roleMirror` leak-survivability invariant is a multi-user concern
Cove doesn't share), drops billing/dashboard/`similarIssues`/`plan-comment`,
and keeps the harness-agnostic execution layer + MCP tools intact.

## Recommendation (final, under the harness-agnostic constraint)

**Pullfrog is the base.** Fork it, drop the proprietary-backend tail
(4b + OAuth/billing/dashboard), replace the GitHub-App ephemeral token model
with a Forgejo PAT passed as a runner secret, point the `gh` MCP tool +
Octokit `baseUrl` at Forgejo `/api/v1`, drop or rework the signed-commits
(`apiCommit.ts`) Verified guarantee, and gate the `gh api graphql` ad. The
harness-agnostic `agents/` layer and the MCP tool server run as-is — opencode
works today, `pi` is one driver file.

openview is out as a base (Claude-only; harness-agnosticism = rewrite).
shippie is out as a base (single harness). **PR-Agent stays the fallback only
if the operator ever decides fixed-tools is acceptable** — it's Gitea-native
and self-hostable, but it's a single fixed-tool harness, not "run any harness."

The real adaptation cost for pullfrog, ranked:
1. **Gitea-vs-GitHub API endpoint mapping** across Octokit-direct tools (4a) —
   the bulk of the work, and it's mechanical mapping, not architecture.
2. **Token model** — swap GitHub-App installation tokens for a long-lived
   Forgejo PAT (or Forgejo scoped tokens rotated per run by a Cove helper).
   Accept the weaker per-run-revocation guarantee; fine for single-operator.
3. **Signed commits** — drop the `apiCommit.ts` Verified path, or wire Forgejo
   signing. Agent commits land as ordinary commits.
4. **Drop 4b** — `similarIssues`, `plan-comment`, `upload`, dashboard trigger
   links. Optionally reimplement `similarIssues` with a local embedding index.
5. **Gate the `gh api graphql` string** in `mcp/gh.ts` (Forgejo has no GraphQL).

The harness-agnostic layer — the part that actually makes it "run any agent" —
costs nothing. That's why pullfrog wins *as the reference* under this
constraint. But "wins as the reference" and "adapt wholesale" are different
questions — and the next one is whether to adapt pullfrog at all, or build.

## Build vs. adapt: is it easier to reimplement our own loops?

This is the question that rebalances everything above. Answer: **for Cove,
yes — a hybrid reimplementation is both less work and lower rugpull risk than
adapting pullfrog wholesale**, and the reason is a clean decomposition of
pullfrog's codebase into two halves with opposite properties.

### The decomposition (verified, not assumed)

I grepped the harness drivers for any import of the forge layer
(`github`, `octokit`, `apiFetch`, `apiCommit`, `roleMirror`, `pullfrog.com`,
`getApiUrl`) — **zero hits.** The drivers are purely harness-management:

```text
agents/claude.ts   1381 lines   — spawn claude-code, OAuth/refresh handling,
agents/codex.ts     957 lines     session labeling, hang detection, teardown
agents/opencode.ts 1585 lines   — spawn `opencode serve`, loopback HTTP SDK,
agents/shared.ts    305 lines      event pumping, activity gating, MCP injection
                  ~4200 lines total, MIT, forge-agnostic
```

Each driver spawns its harness as a subprocess and feeds it the MCP tool
server (`mcp.<name> = { type: "remote", url }`). The harness keeps its native
file-editing/bash/reasoning. The driver handles the *hard* parts: auth-token
refresh races, session resume across gate retries, hang/activity detection,
version-specific harness quirks, clean teardown. That's accumulated
battle-scarring that is genuinely expensive to rediscover.

Opposite half — the multi-tenant security bulk:

```text
roleMirror + token + gitAuthServer + apiCommit + secrets + credentialCheck  ~1343 lines
crossagent + agnostic adversarial test suites                                ~1564 lines
```

This exists to make a multi-tenant GitHub App safe against **untrusted PR
authors** — the role-mirror token scoping, the signed-commits Verified path,
the cross-branch-clobber gate, the subagent tool gates, the untrusted-env
filtering. **Cove is single-operator and trusted.** Most of this bulk solves a
problem Cove doesn't have.

### The hybrid

- **Lift** pullfrog's harness drivers (`agents/*.ts`, MIT, forge-agnostic).
  This is the expensive-to-reproduce part and it doesn't need the
  GitHub→Gitea mapping — it never touches the forge. Attribution preserved;
  the operator already owns `cristoslc/pullfrog-fork`, so the last-good MIT
  commit is safe regardless of upstream's future direction.
- **Rewrite** the forge layer fresh against Forgejo's `/api/v1` (we have the
  swagger at `git.cove/swagger.v1.json`): an MCP tool server
  (pr/issue/comment/review/checkout + a `gh`-shim if wanted), a webhook
  listener, a mention router, a skill loader. Borrow the **shapes** — the
  `Agent` interface contract, the MCP-tool-as-forge-API pattern (pullfrog),
  `.agents/skills/` + `@mention` + webhook-handler structure (openreview),
  Gitea endpoint knowledge (PR-Agent already speaks Gitea). The forge layer
  is maybe 1–2k lines against a stable, documented API.
- **Drop** the multi-tenant security bulk. Defer it until/unless Cove's threat
  model grows (e.g., the forge accepts untrusted external contributions).

### Why this is easier than adapting pullfrog wholesale

Adapting wholesale means: carry ~10k+ lines, retarget the entire MCP tool
server through a GitHub→Gitea translation layer (mapping tax on the whole tool
surface), *and* strip ~2900 lines of multi-tenant machinery that's dead
weight for a trusted operator — all while maintaining a large diff against an
upstream whose business model (proprietary SaaS) diverges from OSS-needs. The
mapping tax alone is the bulk of the work, and it applies to the part we'd
rewrite fresh anyway.

The hybrid sidesteps it: the liftable part (drivers) has no forge coupling, so
no mapping tax; the rewrite part (forge layer) targets Forgejo's real API
natively, so no translation layer. We never carry the dead multi-tenant bulk.

### Why this is lower rugpull risk

- **Forge layer:** ours, small, against a stable Forgejo API. Zero upstream.
- **Harness drivers:** MIT, already forked at `cristoslc/pullfrog-fork`. A
  future pullfrog relicense or deprecation can't reach the last-good commit we
  hold. The maintenance rugpull (forever rebasing a large diff) disappears
  because the drivers are the stable, forge-agnostic half — low churn, and
  when they do change it's harness-version-driven, not business-model-driven.
- **Patterns** (Agent interface, MCP-as-forge-API, skills) are ideas, not
  code — unauditable to rugpull.

The residual risk shifts from *upstream* rugpull to *self-maintenance* of a
small owned codebase — which is the safer side of the trade for a project of
this size.

### Where wholesale-adapt would win instead (the honest conditional)

If Cove's threat model ever grows to include **untrusted external PR authors**
— the forge goes multi-user, or accepts outside contributions, or the steward
processes mentions from arbitrary third parties — then pullfrog's adversarial
suite (the ~2900 lines + 1564 lines of tests we'd drop) becomes valuable and
hard to rebuild. At that point the calculus flips toward taking pullfrog
wholesale (or at least lifting the security layer too). That's a future
conditional gated on a threat-model change, not the current Cove shape.

### Net

Don't adapt pullfrog wholesale. Don't reimplement from a blank file. **Lift
the harness drivers, rewrite the forge layer, borrow the patterns.** That
gives a harness-agnostic, Forgejo-native, self-hostable steward that's smaller
than a pullfrog fork, carries no dead multi-tenant bulk, and has no upstream
whose business model can rugpull it. The `musing → plan → sashay` next step,
if this holds up under a parley, is a plan that scopes the forge-layer rewrite
and lists exactly which `agents/*.ts` files to lift and which `utils/*`
security files to defer.

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

---

## Decision of record

Operator consensus (2026-08-28) on the three open questions above:

1. **Security — keep the prompt-injection defenses, drop only the multi-
   tenant machinery; adopt fail-closed as the methodology.** The trimmed
   posture (~2000 lines kept: pretool gate, fs-denies, push gate, env filter,
   MCP-as-scope-enforcer; ~600 dropped: roleMirror fan-out, OIDC token
   minting, OAuth) plus the Cove-specific repo-config gate (~150 lines,
   fail-closed on misconfiguration). The fail-closed methodology is the load-
   bearing principle: don't try to guarantee repos are configured correctly —
   refuse to run when they aren't, naming the gap.
2. **Patterns — scaffold from openreview, taxonomy + gates from pullfrog,
   config gate is Cove's, impl fresh against Forgejo.** openreview's webhook-
   app shape is the scaffold; pullfrog's MCP tool surface is the taxonomy; the
   security gate layer sits between harness and MCP tools keeping pullfrog's
   own seams; the repo-config gate is Cove-specific; all forge calls written
   fresh against `/api/v1` with no GitHub→Gitea translation layer.
3. **Build vs. adapt — hybrid reimplementation** (from the prior section):
   lift pullfrog's `agents/*.ts` harness drivers (MIT, forge-agnostic,
   battle-scarred), rewrite the forge layer, drop the multi-tenant bulk.

Status moves to **Decided**. Next step is `musing → plan → sashay`: a plan
that scopes the forge-layer rewrite, lists exactly which `agents/*.ts` to
lift, which `utils/*` security files to keep-trimmed vs. drop, and specifies
the repo-config gate's fail-closed checklist. That plan is the prerequisite
to any sashay.

## Correction: the security bulk is not all multi-tenant dead weight

The "drop ~2900 lines of multi-tenant security" line above was too glib, and
the operator's pushback is right: "single-operator and trusted" is **not** a
clean threat boundary. The trust boundary is around *repo/PR content*, not the
operator. A mention-triggered agent reads attacker-controlled text — PR
descriptions, commit messages, vendored code, dependency-update patches, AI-
generated diffs — so the prompt-injection surface is live even for one trusted
operator on their own repos. Re-reading the actual code re-accounts the bulk:

**KEEP — prompt-injection defenses, transfer to single-operator Cove:**

- `agents/claudePretoolGate.ts` + `subagentToolGates.ts` — block state-
  mutating MCP tools from *subagents*. The motivating case is the 2026-05-18
  zed/cloud incident: a review subagent called `checkout_pr` mid-review and
  the orchestrator's next push clobbered an unrelated branch. Any harness with
  subagent delegation has this surface. KEEP.
- `agents/nativeFsDenies.ts` — block the harness's native FS tools
  (Read/Write/Edit) from touching `.git/` (config, hooks, filters, aliases,
  `credential.helper`). The comment is explicit: "a prompt-injected agent could
  plant a git filter or hook via the native edit tool, bypassing the shell
  sandbox entirely." This is the smallest, most directly transferable defense.
  KEEP.
- `utils/secrets.ts` `filterEnv()` / `filterEnvForUntrustedCode()` — strip the
  PAT/webhook-secret/CI-secrets from the harness's subprocess env so a
  prompt-injected `printenv` / `curl` can't exfiltrate them. KEEP.
- `mcp/git.ts:92-118` push gate — block fully-qualified `refs/heads/...`
  refspecs (which bypass default-branch protection), `:refs/heads/main`
  (delete), `+main` (force-push). The cross-branch-clobber / push-escalation
  defense. KEEP.
- The **MCP-as-scope-enforcer pattern** itself — the agent never holds the raw
  forge token; it acts only through the MCP tool server, which exposes scoped
  verbs (comment, review, read-diff) and refuses unscoped ones (delete repo,
  admin, push-to-protected). This is the foundation that makes prompt
  injection survivable when the agent reads attacker-controlled PR text. KEEP.

**DROP — genuinely multi-tenant:**

- `roleMirror.ts` *the per-user permission fan-out* (we have one user; use a
  fixed scoped Forgejo PAT, not a per-run mirror — but keep the minimal-scope
  *invariant*).
- `token.ts` GitHub-App OIDC ephemeral token minting (multi-tenant infra;
  Forgejo has no equivalent anyway).
- OAuth/`credentialCheck` for third-party sign-in.

So the droppable set is ~600 lines, not ~2900. The other ~2000 are prompt-
injection defenses Cove needs. The earlier accounting was wrong; corrected
here.

## The misconfiguration worry: fail closed, don't try to guarantee

The operator's specific concern: "if we drop the security gates we need to be
extra sure forgejo repos can't be misconfigured within cove. I'm not sure we
can guarantee that, currently." The honest engineering answer is you don't
*guarantee* a repo isn't misconfigured — you **fail closed when it is.** That's
a gate neither pullfrog nor openreview has, because pullfrog runs inside GHA
(GitHub's settings + GitHub-App scoping cover it) and openreview trusts its own
Claude core. Cove on Forgejo can't assume either. A Cove-specific **repo-config
gate** runs on webhook receipt, before the agent spawns:

- **Webhook signature verifies** (Forgejo HMAC). If not → 401, no run. (pullfrog
  doesn't have this — it's not a webhook server; Cove is.)
- **Repo is on the allowlist** (explicitly onboarded). If not → ignore silently
  (avoid SSRF / trigger-amplification from a forged payload).
- **Branch protection is on for the default branch** (no force-push, no direct
  push to main). If off → refuse, post a comment "steward disabled: enable
  branch protection on <default>."
- **The configured PAT is scoped** (comment/review/read), **not** admin / push-
  to-protected. If over-scoped → refuse, post "steward disabled: rotate the
  token to a read/comment/review scope."
- **No CI/repo secrets are injected into the agent env.** (Cove controls this at
  the runner level; the gate asserts it.)

Any check failing → no agent spawn, a clear comment or log naming the gap.
~150 lines, Cove-specific, and it's the direct answer to "can't guarantee repos
aren't misconfigured": you don't prevent misconfiguration, you refuse to run on
a misconfigured repo. That converts an unbounded worry into a finite checklist.

## Forge-layer patterns: scaffold from openreview, taxonomy + gates from pullfrog

The forge layer (MCP tool server + webhook + mention router + skill loader)
has two reference sources with complementary strengths — neither is sufficient
alone:

- **openreview (Vercel) is the scaffold.** It's a clean single-purpose Next.js
  webhook app at the *right size and shape* for a single-operator steward —
  `app/api/webhooks/` (webhook handler), `lib/github.ts` (forge calls —
  rewrite as `lib/forgejo.ts` against `/api/v1`), `lib/bot.ts` (mention detect
  + reply/comment posting), `lib/skills.ts` (`.agents/skills` loader),
  `workflow/` (mention → agent → reply flow). Start the scaffold from
  openreview's structure, not pullfrog's (pullfrog is a multi-tenant GitHub
  Action, the wrong shape). openreview contributes **nothing** to security,
  though — it trusts its own Claude core, so it has no gate layer to borrow.
- **pullfrog is the tool taxonomy + the security gate layer.** pullfrog's
  `mcp/` gives the *tool surface* — what verbs a forge steward exposes (pr,
  issue, comment, review, checkout, the `gh`-shim). Borrow that taxonomy,
  implement against Forgejo. And pullfrog's pretool gate + fs-denies + push-
  gate + env-filter (the prompt-injection defenses above) are the gate layer
  that sits *between* the harness and the MCP tools. openreview has none of it.

So the forge-layer synthesis composes cleanly:

```text
                    webhook (scaffold: openreview) ──┐
                  repo-config gate (Cove-specific)    │ fails-closed check
                                       │              │
        harness drivers (lift: pullfrog agents/*.ts)  │
                  │  via loopback MCP                  │
        pretool-gate + fs-denies (lift: pullfrog)  ◀──┘ security layer
                  │                                    (between harness & tools)
        MCP tool server (taxonomy: pullfrog mcp/*;   
                         impl: fresh vs Forgejo /api/v1)
                  │ scoped verbs only
        Forgejo /api/v1
```

- **Scaffold:** openreview's webhook-app shape.
- **Tool taxonomy:** pullfrog's MCP tool surface.
- **Security gates:** pullfrog's pretool gate + fs-denies + push-gate + env-
  filter (prompt-injection defenses).
- **Config gate:** Cove-specific fail-closed repo validation — the part that
  answers the misconfiguration worry directly, which neither reference has.
- **Harness drivers:** lift pullfrog's `agents/*.ts` (the battle-scarred,
  forge-agnostic half from the previous section).
- **Implementation:** all forge calls written fresh against Forgejo `/api/v1` —
  no GitHub→Gitea translation layer anywhere.

The composition point is clean: the lifted harness drivers connect to the MCP
tool server (openreview-shaped scaffold + pullfrog taxonomy + Forgejo impl)
*through* pullfrog's pretool-gate/fs-denies, which is exactly where that gate
layer sits in pullfrog's own architecture. We're not inventing the seams — we're
keeping pullfrog's seams and swapping the forge implementation on one side of
them.