# Plan: Tidesman — a standalone forge steward

**Status:** Scoped — ready for parley/sashay
**Musing:** `docs/musings/2026-08-28-pullfrog-forgejo-adaptation.md` (Decision of record)
**Naming:** `tidesman` — see [Naming](#naming) (etymology, footprint receipts, disambiguation)
**Charter refs:** `PURPOSE.md` ("What Cove Is Not"), ADR-016 (two-tier adoption rubric), ADR-017 (unified admin identity)
**Integration precedents:** `compose/litellm/` + `cli/cove/litellm.py` (`cove litellm` group), `docs/services/speedtest.md`, dagu sashay (local-built image, offline-first)

---

## Naming

**Tidesman** (n.) — historical: a *tide waiter*; the customs officer stationed in port who boarded arriving ships to inspect them. Wiktionary records a secondary sense that reads like a job description for a code reviewer: *"a person who watches public opinion before declaring their own."* Tidesman boards the PR, inspects everything, and only then files the report.

Footprint receipts (checked 2026-08-28): npm package **free**, PyPI package **free**, crates.io **free**, RubyGems **free**, Docker Hub user **free**, `github.com/tidesman` org **free**, no homebrew formula; domains `.com`/`.dev`/`.org` held (parked/dormant — irrelevant; docs live in-repo), `.io` free if a home page is ever wanted. One known neighbor: `JeronimoColon/tidesman-mcp` (★6) — an unrelated MCP server for debugging Linux containers; different category, different surfaces, and we do not publish to npm/PyPI.

**Disambiguation (standalone — no cove seams to lean on):**

1. **Category pairing** — always "Tidesman Bot, a forge steward" in first mentions, listings, and search-indexed text (Vault/Nomad/Harbor model: the noun survives by pinning to its category, which the **steward** coinage owns outright). Substrate rides along only as adapter status — "ships with Forgejo support" — never welded into the identity.
2. **Product/identity split (naming-reopen decision, 2026-08-31).** The **product/repo** is `tidesman-bot` (search-resolving, free across npm/PyPI/crates/Docker Hub/GitHub at check time); the **forge identity and mention** stay bare `@tidesman`, matching the space's convention (@claude, @codex, @copilot, @pullfrog — and claude-code-action's word-boundary match warns that `@claude-bot` would *not* trigger). `-bot` names what the service outwardly is (it does not name a component the project contains, unlike `-agent`/`-mcp`); the bare-word mention keeps the trigger convention intact. Canonical repo registration shifts to the `tidesman-bot` org/handle; the bare word is **not** claimed (the neighbor `tidesman.dev` — now a live, signed product for an Apple-container MCP server — keeps it; the hatnote covers the rest). Decision lands at P0(d).
3. **Pin the category formally** — get listed (Forgejo app directory, awesome-gitea-type lists, once the Forgejo adapter exists) as "Tidesman — a forge steward." One afternoon, compounds forever.
4. **Hatnote** — README, first line:

> *Not to be confused with tidesman-mcp — an unrelated MCP server for debugging Linux containers.*
5. **Escape hatch** — `tidewaiter` (dictionary-primary spelling, ★0 neighbor, no MCP association) if the neighbor ever grows prominent. Held in reserve; a rename, not a re-source.

**Two-identity rule — project ≠ deployment.** Tidesman is a standalone project that must run on **any forge it has an adapter for, without cove**. Cove is its first deployer and its integration host, not its namespace owner:

| Layer | Standalone identity | Cove integration view |
|---|---|---|
| Project / repo | `tidesman-bot` (canonical: `git.cove/cove/tidesman-bot`; push-only GitHub mirror `cristoslc/tidesman-bot` as enhancement — never the source of truth) | same repo |
| Descriptor | *"an always-on, harness- and forge-agnostic forge steward"* | *"Tidesman Bot is Cove's forge steward"* |
| Artifact | image `tidesman-bot:<ver>` (release tarball) | loaded locally as `cove-tidesman:<pinned>` |
| Config | `TIDESMAN_FORGE_URL` + `TIDESMAN_FORGE_KIND` = any configured adapter | set to `git.cove` / `forgejo` |
| Forge identity | bot account `@tidesman` on whatever forge it watches | `@tidesman` on `git.cove` |

Rule: **cove appears at the seams only** (FQDN, container name, CLI group, data dir, 1Password item). The name itself never carries "cove" — the project travels. This is the litellm relationship, generalized: adopted services keep their names; cove namespaces the deployment.

---

## Where this lives: standalone companion repo

A standalone service outside cove, which cove then integrates. Charter, not preference:

- **PURPOSE.md explicitly excludes it from cove.** "What Cove Is Not": *Cove does not ship coding harnesses … or any tool that reads/writes your source code. Cove is infrastructure … The tools themselves are the operator's responsibility **(or a companion project's)**.* A steward that hosts agent harnesses (opencode/claude/codex) is squarely the excluded category; the "or a companion project's" clause is written for exactly this.
- **No upstream image exists** (unlike litellm/speedtest). Tidesman builds and releases its own image; cove integrates a pinned version. Dagu precedent: local-built image for MVP, registry push when CI exists.
- **Cadence decoupling.** Harness drivers churn with harness releases; cove promotes are post-merge, gated events. Tidesman iterates independently of `cove` reinstalls.
- **Image weight + license isolation.** Harness CLIs inside the container; lifted pullfrog MIT code (attribution intact) stays out of cove's codebase.
- **Portability constraint (name and code).** Forge binding is quarantined in adapter files behind one `Forge` interface — the same pattern as the harness `Agent` interface, at the opposite end of the pipe. Gitea rides free (same `/api/v1` family); other forges are new adapters, not rewrites. A second Forgejo — on another machine, or another operator's — is a config change, not a fork.

**What stays in cove:** integration surface only — compose fragment, nginx route, `cove tidesman` CLI group, credentials wiring, docs, tests. Same pattern as `cove litellm`.

---

## Scope

Build a harness-agnostic forge steward with a forge-adapter core (MVP adapter: Forgejo/Gitea):

- **Forge-agnostic core, adapters at the edge.** Forge binding lives in exactly two places: the webhook payload normalizer and the `Forge` adapter. The MCP verb taxonomy, normalized events, harness drivers, gates, and run lifecycle are forge-free. MVP defines the `Forge` interface and ships one adapter; a second adapter is the post-MVP proof of the seam.
- Webhook listener receiving forge events (HMAC-verified), normalized to tidesman's own event types, routing `@tidesman` mentions to agent runs.
- Agent runs **in-container** (Tidesman spawns the harness as a subprocess — pullfrog's driver model), one workspace per run. **The per-run workspace is the only host path bind-mounted** — the workspace, not `~/Documents` broadly.
- MCP tool server as the agent's *only* interface to the forge (MCP-as-scope-enforcer). Agent never holds the raw PAT.
- Security gate layer lifted from pullfrog and trimmed: pretool gate, subagent tool gates, native-FS denies, env filter, push gate.
- Fail-closed **repo-config gate** on every webhook receipt — part of Tidesman itself; cove simply uses it.
- Forge calls written fresh per adapter behind one `Forge` interface — **first adapter: Forgejo (gitea-family `/api/v1`; Gitea rides free)**, swagger from a live instance as the contract. **No GitHub↔Gitea translation layer anywhere**; further forges are new adapter files, not rewrites.
- Skill loading from `.agents/skills/` (same convention as the operator's harnesses).
- Offline LLM via any OpenAI-compatible endpoint; in cove that's the existing LiteLLM service.

### MVP scope cut

- **opencode driver only** for MVP (operator's primary harness; pullfrog has it first-class). Lift `claude.ts`/`codex.ts` later — the `Agent` interface accommodates them without re-architecting.
- **Minimal verb set first**: `checkout`, `read_diff`, `list_prs`, `list_issues`, `comment`, `review`. `gh`-shim, labels, broader verbs are later increments (resolves the musing's open question: the tool *server* is mandatory — it's the scope-enforcer KEEP — its *breadth* grows on demand).

### Out of scope

- Pullfrog 4b: `similarIssues`, `plan-comment`, `upload`, dashboard trigger links.
- Multi-tenant machinery: `roleMirror` fan-out, GitHub-App OIDC minting, `gitAuthServer`, OAuth/`credentialCheck`.
- `claude`/`codex` drivers (later increments).
- Runner-dispatched execution (agent inside a Forgejo Actions runner job) — later enhancement; MVP is in-container.
- `similarIssues` local embedding index (backlog only).
- **Other forge adapters (GitHub, GitLab, …)** — the `Forge` interface and normalized events exist from day one, but MVP ships the Forgejo adapter only. A second adapter is deferred until there's a reason (cove anti-goldplating); the seam's cost ceiling is proven by how small `adapters/forgejo.ts` turns out.

---

## Architecture (scaffold: openreview · taxonomy: pullfrog mcp/* · impl: fresh vs /api/v1)

```
                 Forgejo webhook ────► webhook handler (openreview scaffold shape)
                                        │ HMAC verify + allowlist
                 repo-config gate (fail-closed) ◄── refuse on any gap
                                        │
                     mention router (openreview lib/bot.ts shape)
                                        │
        harness driver (LIFT: pullfrog agents/opencode.ts + shared.ts)
                                        │ via loopback MCP
        gate layer (LIFT-TRIM: pretool gate · subagent tool gates ·
                    fs-denies · env filter · push gate)
                                        │
        MCP tool server (taxonomy: pullfrog mcp/*; impl: fresh per adapter)
                                        │ scoped verbs only, PAT stays server-side
                 Forge adapter — first: Forgejo/Gitea /api/v1 ◄──┘
```

---

## The repo (`tidesman-bot`)

TypeScript. Plain HTTP server (Hono or Express — match the lifted drivers' runtime; see Phase 0 spike) in openreview's module decomposition — **not** Next.js: no Vercel-isms, no `DurableAgent`; openreview contributes only the file/flow shape.

```
tidesman-bot/
  src/server.ts            — HTTP server, /webhook, /healthz
  src/webhook.ts           — forge payload normalize + HMAC verify
  src/configGate.ts        — fail-closed repo-config gate (below)
  src/mentionRouter.ts    — @tidesman mention parse → run request
  src/runs.ts             — run lifecycle: workspace clone, spawn, logs, cleanup
  src/forge/               — `types.ts`: `Forge` adapter interface (derived from the
  │                           MCP verb set); `adapters/forgejo.ts`: typed `/api/v1`
  │                           client generated from swagger.v1.json; later
  │                           `adapters/github.ts`, …
  src/mcp/                — tool server: checkout, read_diff, comment, review, …
  src/mcp/gitPushGate.ts  — port of pullfrog push-gate semantics
  src/agents/             — LIFT ports: opencode.ts, shared.ts, index.ts (attribution headers)
  src/gates/              — LIFT ports: pretoolGate, subagentToolGates, fsDenies, envFilter
  src/skills.ts           — .agents/skills loader
  agents.d/               — Dockerfile (server + node + opencode CLI + git)
  tests/
```

**Runtime note:** pullfrog's drivers are Deno-flavored TS. Default: run the lifted drivers under *pullfrog's* runtime unmodified (their value is the battle-scarring); keep the whole steward on that runtime. Confirmed by Phase 0 spike before Phase 1. This also serves portability — one runtime in the image, no cove assumptions anywhere.

**Release/distribution (offline-first):** CI builds a versioned image tarball. Deploy preflight: if `tidesman:<pinned>` missing from the local image store → print `docker load` instruction, refuse. Dev mode: `TIDESMAN_SRC=<path>` triggers a compose build from a local checkout. Tidesman ships no npm/PyPI packages; the image *is* the artifact.

**State layout (Data in Documents):** cove deploys at `~/Documents/cove-data/tidesman/{workspaces/<run-id>/, logs/, state.json}`; standalone deploys choose their own directory via `TIDESMAN_STATE_DIR`. Workspaces pruned after run completion + N days. Logs per-run, file-backed.

---

## Security inventory (per the musing's corrected accounting)

**LIFT (prompt-injection defenses, ~2000 lines, transfer to single-operator):**

| File (pullfrog) | Trim | Purpose |
|---|---|---|
| `agents/claudePretoolGate.ts` + `subagentToolGates.ts` | keep, minor | block state-mutating MCP tools from subagents (2026-05-18 zed/cloud incident class) |
| `agents/nativeFsDenies.ts` | keep, minor | harness native FS tools can't touch `.git/` (filters, hooks, `credential.helper`) |
| `utils/secrets.ts` (`filterEnv`/`filterEnvForUntrustedCode`) | keep | PAT/webhook-secret never in harness subprocess env |
| push gate (`mcp/git.ts:92-118` semantics) | re-home into our `mcp/` | block refspec bypass, branch delete, force-push |
| MCP-as-scope-enforcer pattern | structural | agent acts only through scoped MCP verbs; refuses unscoped |
| relevant adversarial test suites (subset of ~1564 lines covering the KEPT gates) | keep-trim | regression net for the gates above |

**DROP (~600 lines + 4b):** `roleMirror` fan-out (keep only the *minimal-scope invariant* — the PAT is scoped to comment/review/read), `token.ts` OIDC minting, `gitAuthServer.ts`, OAuth/`credentialCheck`, `apiCommit.ts` signed-commits path, `similarIssues`/`plan-comment`/`upload`/dashboard.

**Add (Tidesman-specific, generically useful to any operator):** repo-config gate + HMAC verify + payload host-pin (anti-SSRF) + single-workspace mount.

---

## Repo-config gate — fail-closed checklist (the misconfiguration answer)

Run on every webhook receipt, before any agent spawn. Any failure → no spawn; post a comment (or log, for silent cases) naming the gap. This gate ships with Tidesman; cove's defaults are simply a correct configuration of it.

1. **HMAC signature verifies** against the webhook secret → else **401**, log only (could be forged).
2. **Repo == allowlisted repo** (`TIDESMAN_ALLOWLIST`, exact `owner/repo` on the configured forge) → else ignore **silently** (SSRF/trigger-amplification defense).
3. **Payload repo host == configured forge host** → else ignore silently (payload-forgery pin).
4. **Default branch protection on** (query `/api/v1`; no force-push/direct-push allowed) → else refuse + comment: "steward disabled: enable branch protection on `<default>`."
5. **PAT scope self-check** (verifies its own token's scopes at startup and on config change; must be comment/review/read, must NOT be admin/owner/write-protected) → else refuse + comment: "steward disabled: rotate token to read/comment/review scope."
6. **Env assertion** — the run's env contains no forge/CI secrets beyond what `envFilter` whitelists (asserted at spawn; belt-and-braces with `filterEnv`).

Known-`TIDESMAN_FORGE_KIND` check at startup (unknown kind → refuse, naming the gap). Startup additionally: **forge reachable**, **PAT valid**, **allowlist non-empty** — else the steward serves but reports degraded on `/healthz` and refuses runs. ~150–200 lines total.

---

## Cove integration changes (first deployment of tidesman)

1. **`compose/tidesman/`** (new, mirrors `compose/litellm/`): `docker-compose.yml` (service `tidesman`, image `tidesman:<pinned>` → container `cove-tidesman`, internal port, `127.0.0.1` bind, bind mount `~/Documents/cove-data/tidesman`, memory limit ~2–4G, restart `unless-stopped`) + env plumbing (`TIDESMAN_FORGE_URL=git.cove`, `TIDESMAN_FORGE_KIND=forgejo`, `TIDESMAN_PAT`, `TIDESMAN_WEBHOOK_SECRET`, `TIDESMAN_ALLOWLIST`, `TIDESMAN_MODEL_*` → LiteLLM endpoint/creds, `TIDESMAN_HARNESSES=opencode`).
2. **`compose/bringup.yml`**: data dir in the loop; cert SANs += `tidesman.cove`; cert validation; hosts entry; .env keys; health wait block; summary print. Webhook registration step against Forgejo API (idempotent hook upsert on allowlisted repos, secret from .env).
3. **`compose/nginx/default.conf.j2`**: upstream + `server_name tidesman.cove` server block (route-whitelisted paths: `/webhook`, `/healthz` — same posture as litellm).
4. **`cli/cove/tidesman.py`** (new): click group `cove tidesman` — `up/down/status/logs`, mirroring `litellm.py` (compose cmd, env injection, 1Password via `cove creds`).
5. **`cli/cove/status.py`**: add `("cove-tidesman", "Tidesman")` + health check (`/healthz` via `Host:` header, `--no-sudo` compatible).
6. **`cove creds`**: new 1Password item **`Cove Tidesman`** (fields: forgejo PAT, webhook secret) — its own forge bot account **`@tidesman`** on git.cove (own identity, own scoped PAT — *not* the Cove Admin identity; ADR-017-compatible: new item, keyed to `tidesman.cove`).
7. **`docs/services/tidesman.md`**: quick start, hardening table (litellm-doc style), config gate explanation, harness/model configuration offline via LiteLLM. Notes that Tidesman is deployable outside cove against any supported forge.
8. **`docs/test-coverage-matrix.yaml`**: rows for webhook auth, config gate (each fail-closed branch), mention routing, MCP scope refusals, push gate, run lifecycle cleanup.
9. **Tests** (per AGENTS.md gates):
   - unit: HMAC, config gate branches, mention parse, push-gate refusals, env filter (lifted gates' suites reused);
   - integration (`-m "e2e and not staging"`): tidesman ↔ staging Forgejo — mention → run → comment; misconfigured repo → refuse + comment; forged payload → 401/silent;
   - staging (`-m staging`, via `scripts/staging/`): full deploy against `https://127.0.0.1:8443`.
10. **`CHANGELOG.md`** + README service list. A **standalone install doc** (`tidesman/README.md`) covers non-cove deploys: one compose file + `TIDESMAN_*` env + webhook.

---

## Phases

**P0 — Spikes & decisions** (½–1 session; gates everything else)
- (a) Driver runtime reconciliation: run pullfrog's `agents/opencode.ts` + `shared.ts` unmodified in a container against a local Forgejo stub; confirms runtime choice for the whole image.
- (b) Forgejo event reality-check: confirm `issue_comment`/`pull_request` webhook payloads + `comment.created`; capture shapes → normalize spec.
- (c) Swagger→typed-client spike: generate `/api/v1` types from `swagger.v1.json`; confirm MVP verb set maps 1:1; type the `Forge` adapter interface from the verb set (interface-first, then generate the Forgejo client inside the adapter).
- (d) Scaffold `git.cove/cove/tidesman-bot`; license/attribution headers for lifted code (MIT preserved, provenance per file); optional GitHub mirror config (`cristoslc/tidesman-bot`, push-only).

**P1 — Happy-path skeleton E2E** (~1–2 days)
Steward container + webhook + HMAC + allowlist + mention router + single verb (`comment`) with opencode-in-container. Success = `@tidesman ping` produces a forge comment. No gates yet — throwaway risk accepted.

**P2 — Security layer in** (~1–2 days)
Lift drivers' gate seams + pretool/fs-denies/env-filter/push-gate; MCP-as-scope-enforcer live; PAT proven unobservable from harness env (test); subagent tool gate test.

**P3 — Full MVP surface** (~2 days)
Remaining MVP verbs; `configGate` branch by branch; workspace lifecycle (clone→run→push via MCP only→cleanup); skills loader; per-run logs; retention pruning.

**P4 — Cove integration (first deployment)** (~1 day)
All cove-repo changes above; image pin + `docker load` path documented; cove docs; coverage matrix. The standalone `README.md` (any-Forgejo install) ships in the same pass so the project is never cove-entangled.

**P5 — Staging e2e + promote** (~½ day)
Staging run green → fj draft PR → test gate → merge → `cove` reinstall promotes integration; tidesman first release tag.

Deferred increments (post-MVP): claude/codex drivers; `gh`-shim verb; labels verb; runner-dispatch execution mode; `similarIssues` local index.

---

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Drivers assume GHA env (OAuth/refresh, hang detection tuned to actions runner) | P0(a) spike before committing; if claude driver drags GHA assumptions, MVP still ships on opencode |
| Forgejo `issue_comment` payload/fire semantics differ from assumption | P0(b) spike captures real payloads first |
| Agent container tooling gaps (no per-repo language toolchains in-container) | MVP verbs are review/comment-centric; runner-dispatch mode is the planned answer for test-running |
| Workspace blast radius | only the per-run workspace is bind-mounted; everything else container-local |
| PAT over-scope drift | config-gate check #5 fails closed, not silently |
| Upstream license drift (pullfrog) | MIT + already forked (`cristoslc/pullfrog-fork`); per-file provenance headers |
| cove/tidesman version skew | compose pins image tag; cove wheel carries no tidesman code |
| Name-neighbor confusion (`tidesman-mcp`) | no shared surface (no npm/PyPI/hub under the name); hatnote in README; cove-prefixed seams |
| Mirror split-brain (git.cove ↔ GitHub) | canonical = git.cove; GitHub is push-only mirror, never merged back |
| Forge-agnosticism becomes gold-plating | interface-first only; one adapter in MVP; second adapter gated on demand |

---

## Open items for the sashay

- ~~Harness account naming~~ — resolved: bot account **`@tidesman`** on git.cove (1Password item "Cove Tidesman").
- Auto-webhook-registration for allowlisted repos at bringup vs. an explicit `cove tidesman hook add <repo>` — recommend automatic; single-tenant simple.
- LiteLLM default model id for `TIDESMAN_MODEL_*` — decide at P4 against the operator's current model list.
- ~~Whether/where to claim the `tidesman` org + Docker Hub user~~ — resolved (naming reopen, 2026-08-31): the bare word is **not claimed**; product/repo registers as `tidesman-bot` (free at check), bare `@tidesman` remains the forge identity. `portreeve` (zero-collision, verified) observed but left unclaimed as future vocabulary.