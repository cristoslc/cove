---
title: "Pullfrog → Forgejo: what actually ports, what doesn't"
created: 2026-08-28
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

## Layer 4 — the object-scoped MCP tools — HARD conflict with Cove offline-first

This is the one I didn't expect. `mcp/pr.ts`, `mcp/issue.ts`, `mcp/comment.ts`,
`mcp/review.ts` etc. don't hit GitHub directly. They go through `apiFetch` →
`getApiUrl()` → `utils/apiUrl.ts`, which resolves to **`https://pullfrog.com`**
(Pullfrog's own hosted backend), not `api.github.com`. The backend brokers
GitHub access on the action's behalf.

That's a hard dependency on an external hosted service. For Cove it's a
non-starter as-is:

- PURPOSE.md: "No public forge dependency… The operator owns all instances
  end-to-end." A tool whose object-scoped operations round-trip through
  `pullfrog.com` is exactly the "third-party rugpull must not break core"
  case Cove is chartered against.
- The airplane test: with WiFi off, `apiFetch` to `pullfrog.com` returns
  nothing. The object-scoped tools — which are the *below-triage* path, the
  one that works without a `gh` token — go dark.

So adapting the object-scoped layer for Forgejo isn't "point gh at a new
host." It's "replace the `pullfrog.com` backend with something that talks to
the local Forgejo REST API directly." That's either a local shim that
re-implements the backend's GitHub-proxy contract against Forgejo's `/api/v1`,
or a fork of the MCP tools to call Forgejo directly. Either is the bulk of
the adaptation work.

## So: viable, but the cost is in layer 4, not layer 1

| Layer | Ports to Forgejo? | Cost |
|---|---|---|
| `gh` MCP tool (generic CLI passthrough) | yes, with GraphQL caveat | small — gate the "graphql available" string, configure `GH_HOST` |
| Signed commits (`apiCommit.ts`) | no cleanly | medium — drop Verified guarantee or wire Forgejo signing |
| Ephemeral token model (`roleMirror`/`token`/`gitAuthServer`) | no architecturally | medium — long-lived PAT + accept weaker leak guarantee (fine for Cove's model) |
| Object-scoped MCP tools (`pr`/`issue`/`comment`/`review` via `pullfrog.com`) | no — hosted backend dependency | **large — this is the actual project** |

The earlier musing's framing ("no new interface required, just configure
`gh`") was wrong. It's true *only* for the `gh`-CLI tool layer. The
object-scoped tools — the ones that actually make pullfrog *pullfrog* (PR
review, issue triage, comment threading, the `@pullfrog` mention loop) —
depend on a hosted backend that has to be replaced with a local
Forgejo-talking equivalent. That's the adaptation work. Layer 1 is a
warm-up; layer 4 is the job.

## Open question to sit with

The honest question isn't "can we adapt pullfrog for Forgejo" (yes, at the
cost above). It's whether the object-scoped tool layer is worth re-implementing
against Forgejo's REST API, or whether the `gh`-CLI tool alone — agent drives
`gh pr`, `gh issue`, `gh api` directly — is enough for a single-operator forge
where there's no multi-user permission mirror to enforce anyway. The
`roleMirror` machinery exists to constrain a *multi-user* GitHub App; in a
single-operator Cove, the operator's PAT *is* the right scope, and the
object-scoped layer may be solving a problem Cove doesn't have. Worth a
parley before committing to re-implementing layer 4.