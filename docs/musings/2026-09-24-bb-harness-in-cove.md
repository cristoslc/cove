# Muse: bb as Cove's agentic harness — and self-hosting the getbb.app piece

**Date:** 2026-09-24
**Trigger:** "what kind of agentic harness setup were we looking at building into cove. Is it worth adding a getbb.app self-hosted configuration to cove?"
**Trove:** `docs/troves/harness-catalog/` (synthesis crawled June 2026)
**Rubric:** ADR-016 (Two-Tier Service Adoption Rubric)

## What we were building (per the harness-catalog trove)

The June 2026 trove surveyed web/desktop surfaces for coding harnesses and landed on:

1. **`opencode.cove` behind nginx** — the concrete recommendation. Add an nginx block in `default.conf.j2` proxying an OpenCode web container at `127.0.0.1:4096`. Rationale: sidesteps OpenCode web's open basic-auth bugs (#9066, #18325, #17376), keeps the `*.cove` URL pattern, and sets the template for future harness sites.
2. **Tier-2 wrapping as follow-up** — Claude Code ACP / ttyd-wrapped harnesses for server-side sessions were flagged as gaps, not decisions.
3. **Candidate UIs** — CodeNomad (1.9k★), Palot, CloudCLI, opencode-manager etc. were cataloged; no pick was made.

The trove predates bb's arrival and predates the operator adopting bb as the daily driver (this session is opencode running inside bb).

## What changed since: bb ate the question

- **bb** (github.com/get-bb/bb, MIT, get-bb org) shipped Aug 2026 and won the orchestrator slot the trove was trying to fill. Multi-provider (Claude Code, Codex, OpenCode, Cursor, Pi, Grok, Hermes), thread-based, local-first, extensible-by-prompt.
- The "which web UI for OpenCode" question is now mostly moot — bb's web/desktop app *is* the harness surface, and it orchestrates OpenCode rather than competing with it.
- The trove's nginx recommendation survives in modified form: the harness surface worth exposing at `*.cove` is **bb**, not OpenCode web.

## What "self-hosted getbb.app configuration" actually is

getbb.app is **not** the bb server — it's the optional **bb Connect relay** (remote access is a plugin; the relay is one of its functions). The bb server itself is local-first and already self-hosted by design: one machine runs `bb-server` (threads, SQLite DB, settings, loopback by default); every other machine/app connects as a client.

Two remote-access modes exist:

| Mode | What it is | getbb.app dependency |
|---|---|---|
| **bb Connect** | Paired relay via `<handle>.getbb.app`; AASA universal links, mobile push, pairing dashboard | Full (cloud relay + auth) |
| **Direct URL** | Any HTTPS URL reachable from the client — docs name "a private Tailscale Serve URL" | None |

So a "getbb.app self-hosted configuration in cove" decomposes into two very different proposals:

1. **Self-host the relay function** (replicate Connect pairing/push/universal-links inside cove). Not worth it — those are product features of the Connect plugin, not something cove should re-implement.
2. **Self-host the ingress** (expose the local bb server through cove so phone/remote clients use Direct URL instead of the relay). Cheap, aligned, and cove-shaped.

## The anti-recommendation: do not containerize the bb server

> **Superseded 2026-09-25** — see the addendum at the end. Containerized harnesses are now the decided architecture, and the bb server itself moves into cove's compose stack.

Running `bb-server` as a cove compose service would orphan it from everything it needs, which is all host-resident:

- provider subscriptions/logins (Claude Code, Codex, etc. — billed on the operator's own accounts, authenticated on the host)
- project checkouts, worktree hooks (`.bb-env-setup.sh`), SSH keys, git remotes
- the host daemon + launchd service model bb is built around (`bb guide server`)

bb belongs in the same category as the operator's CLI toolchain — host-level, not stack-level. Cove's role is ingress and forge, not runtime.

## ADR-016 Tier 2 scorecard (for the record)

- **Cost-to-graduate:** PASS — MIT, free, agents billed by your own provider subscriptions. No cliff.
- **Feature parity (self-host vs managed):** PASS — the server *is* the self-host; Connect relay is the only cloud piece, and a Direct URL bypasses it.
- **Exit cost:** LOW-MODERATE — SQLite threads DB + data-dir copy; AGENTS.md/skills/plugins are plain files. SQLite is single-machine (trove F2), so tier-2 session sync stays hard, but export/import works.
- **Fork-safety (compound):** PASS-ish — OSI MIT license; community young (project went public Aug 2026) but active, with third-party coverage (flaviocopes source-read, deepwiki, reviews) and an active plugin ecosystem. Watch, don't gate.
- **Governance:** single-vendor (get-bb org), no foundation. Secondary factor; not disqualifying per ADR-016.

Verdict: bb passes Tier 2 comfortably as a **host-level DX tool**, with cove contributing ingress only.

## What's actually worth doing (sashay-able)

1. **Direct-URL ingress in cove:** expose the loopback bb server through cove's existing TLS path — either `bb.cove` via the nginx template (same pattern as the trove's `opencode.cove` recommendation) or a Tailscale serve route. Replaces the getbb.app relay for remote/phone access.
   - *Unverified:* whether desktop/web pairing works cleanly over a plain direct URL (mobile app Direct URL mode is documented; desktop pairing flow over direct URL needs a check), and what bb's WebSocket/auth expectations are behind a reverse proxy.
2. **Forgejo as a bb remote:** bb projects map to repos; `git.cove` fits the existing remote convention (`fj` secondary remote) for threads that push to cove.
3. **Drop `opencode.cove` from the roadmap** unless OpenCode-web is wanted standalone for a headless/tier-2 box; bb already covers the surface.
4. **Keep ttyd/ACP tier-2 wrapping parked** — revisit only if a server-side, headless harness (e.g. on a NAS/always-on box) becomes a real need.

## Open questions

- Does bb's web app authenticate fine behind nginx proxying (headers, websockets)? Needs a 30-minute spike.
- Does the bb mobile app's Direct URL mode support everything Connect does minus push (thread steering, environments)? Documented as read/write for threads; environments/worktrees support unverified.
- If the Mac sleeps, bb is unreachable (server-machine rule). Does that matter for a phone-first access pattern, or is the always-on box (swain-box / future tier-2 host) the better bb-server home? That flips the ingress question: cove's nginx would front a *remote* bb server instead of a local one.

## Follow-up (2026-09-25): operator decisions + the containerization question

**Decisions made in parley:**

1. **Adopt bb; drop the `opencode.cove` server from the roadmap.** bb is the harness surface.
2. **bb lives with cove** — i.e. on this Mac, not a separate always-on box. The Mac-asleep risk is accepted for now.
3. **Ingress over relay, confirmed.** Hostname candidates floated: `ade.cove`, `agenticide.cove`. Verdict: pick **`ade.cove`** (one name, short). `agenticide.cove` parses as "agenticide" and is a mouthful. `bb.cove` is the literal alternative if we ever want product-literal naming. One hostname for the IDE; add more only if a second surface actually exists.

**The containerization question: do we need a harness container (mounts projects, pulls from `git.cove`, ships opencode + pi + codex + claude)?**

What it buys:

- **Isolation** — agent execution off the host config; dirty experiments contained.
- **Portability** — the same image lifts to an always-on box later if the Mac-asleep trade ever flips.
- **Reproducibility** — pinned CLI versions, cove-managed creds, IaC all the way down (`cove ade up` as a profiled service, litellm/runner pattern).

What it costs / frictions to solve:

- **Auth is the hard part.** Provider CLIs are subscription-authenticated with refreshable tokens (Claude Code keychain, Codex, OpenCode). Bind-mounting host credential dirs read-write works but guts the isolation story. Static API keys from Vault (`cove creds` → compose env) are clean IaC but switch billing from subscriptions to API rates. Trade-off to decide per provider.
- **bb integration shape.** Two options: (a) container as a **bb machine** — bb host daemon inside, connecting to the server via direct URL; fits bb's model, keeps threads/environments first-class. (b) container as a dumb runtime bb knows nothing about — loses the whole point. Verified on host: only the `manual` machine provider is installed; the Mac is the only machine. So (a) is greenfield — needs the daemon in-container + a reachable server URL.
- **Loopback problem.** bb server listens on `127.0.0.1:38886` (verified via `BB_SERVER_URL`). The cove nginx container cannot reach host loopback; Colima gives `host.lima.internal` but bb must bind wider (config change) or a socat sidecar on the host forwards. Same problem blocks both `ade.cove` ingress *and* the container-as-machine enrollment — solving it once serves both.
- **Projects: clone, don't bind-mount.** Inside the container, clone from `git.cove` (dnsmasq at host:5353 is reachable; mkcert CA must be injected into the image trust store) rather than bind-mounting host working copies — avoids virtiofs slowness and collides less with host worktree hooks. Host checkouts stay the operator's; container clones are per-thread/per-machine scratch.

**Sequencing recommendation (revised):**

1. **Phase 1 — ingress only:** solve loopback (bind bb wider or socat), add `ade.cove` to `default.conf.j2`, spike auth (nginx basic auth vs bb's own direct-URL auth — unverified), test phone + desktop pairing over direct URL.
2. **Phase 2 — `ade` container as bb machine:** profiled compose service, daemon in-container, clones from git.cove, creds via Vault with a per-provider subscription-vs-API-key decision. Gate this phase on the spike result: if bb's native worktree/sandbox isolation covers the need, the container may shrink to "nice to have."
3. **Phase 3 — portability:** same image on the always-on box when/if that day comes.

**New open questions:**

- Does bb direct-URL mode carry its own auth (token/pairing) or is loopback-trust the only mode today? Gates `ade.cove` exposure.
- Does the bb host daemon run sanely in a Linux container (launchd-free service model)? It has a systemd path per `bb guide server`, so likely yes.
- Colima virtiofs vs in-container clones: confirm git.cove TLS + DNS resolution from inside a cove-network container (mkcert CA injection).

## Addendum (2026-09-25, later): containerization is the decision, not an option

Operator pushback, accepted: **cove's job is isolation, and bb on the host has full access. Host-side agent execution is off the table. Containerized harnesses are the only option.** The Phase-2 gate ("maybe the container shrinks to nice-to-have") is withdrawn.

### Revised architecture

bb splits along its own seam — control plane vs execution machines:

- **bb-server: a cove compose service** (stateful volume for SQLite + settings). This supersedes the earlier anti-containerization stance, and it dissolves the loopback problem: execution containers on the cove docker network reach the server at `http://bb:38886` directly. The Mac reaches it via Colima's loopback port mapping; the desktop app becomes a plain client.
- **`ade` containers: cove profiled services, one per harness role.** bb host daemon inside each, enrolled to the server over the cove network (manual provider, scripted enrollment — same IaC shape as the Forgejo runner). Projects clone from `git.cove` inside the container; mkcert CA baked into the image.
- **The Mac enrolls no execution machine.** It runs the desktop/web client only. Agent threads never touch host state.
- **Ingress unchanged:** nginx fronts the server UI at `ade.cove`; web + phone clients connect over TLS.

### The one hard problem left: provider auth

Subscriptions (Claude Code keychain, Codex, OpenCode logins) authenticate per machine and don't belong to the host anymore. Options:

1. **Long-lived named containers with persistent volumes** — log in once per container, creds live in the volume, isolation preserved, subscription billing kept. Containers become pets, not cattle.
2. **Static API keys from Vault** (`cove creds` → compose env) — clean IaC, ephemeral-friendly, but billing moves from subscriptions to API rates.

Option 1 first; option 2 where a provider has no container-friendly login. Decide per provider at build time.

### Revised sequencing

1. Containerize bb-server in compose; verify desktop app connects via mapped port; `ade.cove` nginx site.
2. `ade` container as enrolled machine: daemon in-container, git.cove clone, mkcert trust, provider auth per above.
3. More harness roles (pi, codex, claude) as additional profiled instances of the same image.

### Posture decision (2026-09-25, later still): step-up enrollment, not mandatory containers

Operator question: does this fold into `cove project`? Is enrollment per-project? Should the host be default-enrolled with containers as the step-up?

Resolution:

- **Enrollment is per-machine in bb, not per-project.** One enrolled `ade` container hosts many bb projects (each a git.cove clone). Per-project enrollment is optional extra isolation, not a requirement.
- **Two scopes, two homes:**
  - Platform scope — bb-server container + shared machine containers = `cove up` / profiled services (runner/litellm pattern). Not per-project.
  - Per-project scope — a project's own harness container = the `cove project` model from `mcp-isolation-and-dynamic-mounts.md` (project `cove.yaml` declares needs, `cove project up .` provisions). bb gives that model its first concrete consumer. **Note: `cove project` does not exist in the CLI today** (verified against `cove --help`; the MCP musing's claim that it does is stale) — it's planned surface.
- **Default posture: server containerized, host default-enrolled.** The host daemon already runs on the Mac, so enrollment is free the moment the server is reachable at its mapped port. This preserves continuity: existing projects/threads reference host paths and keep working through the host machine; nothing migrates. (The prior "containerized-only" stance applies to cove-*provisioned* project execution; the operator's own host threads are the operator's own device.)
- **Step-up:** `cove ade up` provisions a machine container; later, `cove project` with `harness: container` in `cove.yaml` makes per-project containerized execution declarative. Isolation is supplied, not forced.

### Open questions (replacing the earlier ones)

- Does the bb host daemon enroll over plain HTTP inside the cove network, or does it demand the server's public URL shape? (Runner-style scripted enrollment needs this answered.)
- Do provider CLIs tolerate volume-persisted logins across container restarts? (Spike per provider.)
- Does the mobile/web client work against a compose-hosted server behind nginx — headers, websockets, pairing?
- Where does bb's own data-dir convention land in a container (`BB_DATA_DIR` / XDG paths) so thread state survives image upgrades?
