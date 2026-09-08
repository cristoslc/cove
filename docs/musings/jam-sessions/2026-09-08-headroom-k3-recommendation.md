---
title: "Headroom standalone vs LiteLLM for Cove — certified recommendation"
created: 2026-09-08
status: Draft
---

# Headroom standalone vs LiteLLM for Cove — certified recommendation

A jam session on one question: should standalone Headroom
([headroomlabs-ai/headroom](https://github.com/headroomlabs-ai/headroom) —
70.7k★, Apache-2.0, Rust+Python, own proxy at :8787, `headroom wrap opencode`,
MCP server, cross-agent memory, output-token shaping) run **in addition to** the
current LiteLLM router + Headroom sidecar (Option A), or **instead of** LiteLLM
entirely — agents point at the standalone Headroom proxy, which passes through
to Ollama Cloud directly, no LiteLLM (Option B)?

Prior art read first, in order: `docs/musings/litellm-headroom-context-proxy.md`,
`docs/musings/litellm-hardening.md`, `docs/services/litellm-proxy.md`,
`docs/tech-debt/litellm-test-drift.md`,
`docs/tech-debt/cove-litellm-compose-profile-flag.md`,
`docs/musings/observability-prometheus-otel.md`,
`docs/musings/2026-08-28-pullfrog-forgejo-adaptation.md`, plus the deployed
surface (`compose/litellm/docker-compose.yml`, `compose/litellm/config.yaml.j2`,
`compose/litellm/Dockerfile`, `cli/cove/litellm.py`,
`compose/nginx/default.conf.j2`). Then the live web: Headroom README, docs
(docs.headroomlabs.ai, headroomlabs-ai.github.io), LiteLLM security advisories,
Issue #76, DeepWiki source indexation.

## One framing correction up front

The July 2026 musing and the deployed stack both built on **"Headroom inside
LiteLLM"** — the `ghcr.io/chopratejas/headroom` sidecar image called by
LiteLLM's `headroom_settings:` guardrail. The standalone project under review
here is the **same lineage, different deployment shape**: a self-contained
Rust-core + Python-supervisor proxy at port 8787 with its own routing, MCP
server, memory store, `wrap` CLI, and output shaper. Option A keeps "Headroom
as a LiteLLM guardrail." Option B runs "Headroom *is* the proxy." They are not
two ways of deploying the same thing; they are two architectures. That is the
decision.

## Steelman for Option A — keep LiteLLM router + Headroom sidecar (in addition)

The honest case for A rests on four load-bearing facts.

**1. Cove's model aliasing is a real, configured feature — and LiteLLM alone
provides it today.** `compose/litellm/config.yaml.j2` declares four aliases
(`deepseek-v4-flash`, `deepseek-v4-pro`, `glm-5.2`, `kimi-k2.7-code`), each
mapping an OpenAI-compatible `openai/<name>` upstream at
`https://ollama.com/v1` behind one `OLLAMA_API_KEY`. That is per-model aliasing
onto a *custom OpenAI-compatible upstream*. Headroom standalone routes at the
**provider/endpoint** level (`OPENAI_TARGET_API_URL`, `--backend
openrouter|azure|bedrock|vertex_ai|anyllm`, per-request `x-headroom-base-url`)
— not per-model-alias. Its only model-rewrite knob,
`HEADROOM_MODEL_ROUTER_ENABLED` + `HEADROOM_MODEL_ROUTES` (PR #1706), is
**cost-aware auto-routing** (send small/tool-free calls to a cheaper model) —
and per the CHANGELOG it is applied **only on the Anthropic `/v1/messages`
path**, not the OpenAI-compatible path opencode uses. It is not "alias
`deepseek-v4-flash` → `openai/deepseek-v4-flash` at `ollama.com/v1`."
Replicating the alias layer on Headroom-alone means reimplementing it (or
pointing the agents at raw Ollama model names and losing the Cove alias
indirection entirely). Anti-rationalization searches below.

**2. LiteLLM's posture, while CVE-heavy, is now *understood and bounded* — and
the hardening investment is sunk.** `docs/musings/litellm-hardening.md` lays out
the threat model honestly: single-user, localhost-only, trusted operator. The
July security landscape (16+ CVEs, March 2026 TeamPCP supply-chain compromise
via the Trivy Action) is mitigated by deployment shape, not by code trust:
`compose/litellm/docker-compose.yml` binds `127.0.0.1:4000` only, runs
`read_only: true`, tmpfs for logs, memory-capped at 512M, pins
`litellm==1.84.0` in a multi-stage build (`compose/litellm/Dockerfile`). The
admin identity is IaC-seeded from 1Password (`cli/cove/litellm.py`,
ADR-017-aligned) — no default `admin@example.com`. The master key lives in a
shared 1Password item cached in Vault, injected into compose `.env`, never
hand-typed. That credential-concentration risk (one place holding
`OLLAMA_API_KEY`) is *the same* risk a Headroom proxy would carry — moving
where the key sits does not de-concentrate it. **Key concentration is a wash.**

**3. The security-surface delta is real but smaller than it first looks, and
it's a *trade*, not a removal.** Dropping LiteLLM removes its CVE stream — and
that stream is still flowing: the advisory page today shows ten entries on page
1 alone, the latest `GHSA-3cv6-jpf6-8222` (authenticated SSRF + credential
exfiltration via unvalidated routing params) published **2026-08-26**, thirteen
days ago. But Option B *adds* Headroom's surface: `CVE-2026-32920`
(auto-install of untrusted plugins), `GHSA-ff98-w8hj-qrxf` (plugins run with
full system privileges), and the CompressionAttack vector (adversarial input
that becomes a prompt injection *after* compression) — a risk class that exists
only because compression exists. The July musing rated CompressionAttack
"manageable for Cove" (the attacker is the trusted operator), and Headroom's
own releases have been shipping fixes at a steady clip (the same release cadence
that produced `fix(opencode): ship the transport hook-shim` #2878 and `metrics:
record per-extension token savings` #2371). Net: B trades a large, well-mapped,
mostly-network-gated CVE surface for a smaller, less-mapped one plus a novel
attack class. That is a genuine improvement in raw count — but not the
unambiguous win "dropping LiteLLM removes its CVEs" implies.

**4. IaC-first bias and the existing test investment argue for *fixing*, not
*replacing*.** Cove's charter is infrastructure-as-code: every service declared
in compose + bringup + seeds + CLI provisioning, no hand-config. LiteLLM is
fully in that world (`cove litellm up/down/status/logs`, `config.yaml.j2`
rendered, credentials provisioned). There is real debt
(`docs/tech-debt/litellm-test-drift.md` — ~9 failing tests where the tests
encode a stricter posture than the deployed config, and
`docs/tech-debt/cove-litellm-compose-profile-flag.md` — `cove litellm up`
broken on Docker Compose v5's removed `--profile` flag). That debt is fixable
in place. It is not evidence that the architecture is wrong; it is evidence the
tests and CLI drifted from the config — exactly the class of problem a sashay
fixes.

## Steelman for Option B — replace LiteLLM with standalone Headroom (instead-of)

The honest case for B does not rest on "LiteLLM bad, Headroom good." It rests
on architectural mismatch.

**1. The single biggest finding of this jam: nothing in Cove actually *uses*
the LiteLLM alias layer today.** I grepped the entire repo for the aliases, the
upstream, and OpenAI-compatible harness bindings
(`litellm.cove`, `openai-compatible`, `@ai-sdk/openai`, `ollama.com/v1`,
`deepseek-v4-flash`, `kimi-k2.7-code`, `glm-5.2`) across json/ts/py/md — **zero
hits** outside the litellm config itself and the docs about it. The opencode
integration in this repo's harness instructions does not route through
litellm.cove. The pullfrog musing (`2026-08-28-pullfrog-forgejo-adaptation.md`)
*proposes* `litellm.cove` as a future PR-Agent fallback endpoint — a proposal,
not a consumer. So the "existing alias investment" argument is weaker than it
reads: the investment is a configured capability with no in-repo callers. If
the consumers are all out-of-repo (the operator's personal harness configs
elsewhere), that is a different situation and the operator should say so — but
on the evidence in this repo, the alias layer is speculative infrastructure.

**2. Headroom standalone is now a first-class opencode integration, not a
proposal.** The July musing cited GitHub Issue #76 ("headroom-opencode npm
package") as *proposed, not built*. It is now **closed and shipped**:
`plugins/opencode/` exists in the repo, exports `HeadroomPlugin` for in-process
transport interception, and the docs have a full OpenCode page
(`docs.headroomlabs.ai/docs/opencode`). `headroom wrap opencode` starts the
proxy, injects a `provider.headroom` config block, registers MCP tools, and
launches. This is not a shim — it is the integration the July musing was
waiting for. The "we'd have to build the opencode bridge" objection is moot.

**3. Standalone Headroom gives Cove things LiteLLM+sidecar structurally
cannot.** The sidecar architecture gives compression only. Standalone Headroom
adds: **output-token shaping** (verbosity steering + effort routing, trimming
what the model *writes back* — on Opus-class models output is 5× input cost;
LiteLLM has no equivalent), **cross-agent memory** (one store across Claude /
Codex / Gemini / Grok with dedup — orthogonal to a router), an **MCP server**
(`headroom_compress` / `headroom_retrieve` / `headroom_stats`), **`headroom
learn`** (mines failed sessions, writes corrections to AGENTS.md — directly
aligned with this repo's harness conventions), and a **CCR retrieve tool** that
makes compression reversible and model-callable. If Cove's agents are going to
live behind a compression layer, B is the version of that layer that is
actually a *platform* rather than a guardrail.

**4. The security-surface argument *does* favor B, once weighed honestly.**
Per the A-side steelman this is a trade, not a removal — but the trade favors
B on two axes the musing cares about. First, **CVE *velocity***: LiteLLM's
advisory page is adding moderate-to-critical entries on a roughly monthly
cadence *right now* (Aug 26 SSRF, Jun 30 file-read/path-traversal, May 28 host-
header auth bypass, Apr 21 MCP command exec, Apr 20 SQLi). Headroom's page shows
**one** security entry. Second, **supply-chain posture**: the March 2026
TeamPCP compromise hit LiteLLM's *own CI/CD* (compromised Trivy Action → PyPI
creds → malicious wheels). That is a demonstrated, realized compromise of the
exact pipeline Cove pins against. Hash-pinning bounds it, but the hardening doc
itself lists "vendor the wheel" as an *unmet* mitigation. Headroom's Rust-core
+ pinned-release posture is not immune, but it has not had its supply chain
compromised. On balance, B is the *safer* dependency to carry.

**5. IaC is not a blocker for B — it's a small, well-shaped project.**
Standalone Headroom deploys as a container (`ghcr.io/headroomlabs-ai/headroom`,
docker-native install exists), reads all config from env (`OPENAI_TARGET_API_
URL`, `HEADROOM_BEACON=off`, `HEADROOM_MODEL_ROUTES`), exposes `/health`
`/metrics`, and binds 127.0.0.1. Wiring it Cove-style means: one compose
service, one nginx server block following the exact same variable-upstream
pattern already used for litellm
(`compose/nginx/default.conf.j2:130-153`), `HEADROOM_BEACON=off` and
`HF_HUB_OFFLINE=1`-equivalent for offline-first, secrets via `cove creds` the
same way litellm does it. That is a normal Cove service, not a special case.

## The deciding considerations, weighed

Five things move the needle. None is close; together they tilt.

**Routing/aliasing (favors A, but mostly vacuously).** A is the only option that
preserves Cove's configured Ollama-Cloud alias indirection. But no in-repo
consumer uses those aliases, so the preserved capability is dormant. If the
operator's *actual* agents (out-of-repo opencode configs) DO call
`litellm.cove/v1` with `deepseek-v4-flash` et al., that is live usage the repo
can't see — and it is the single piece of information that would flip this
recommendation. Flagging explicitly.

**Security surface (favors B, net).** Trade, not removal — but CVE velocity +
the realized supply-chain compromise make Headroom the lower-risk carry, and
the CompressionAttack class is acceptable under Cove's trusted-operator threat
model per the July musing's own assessment.

**Offline-first (favors neither cleanly; both need ops discipline).**
LiteLLM+sidecar phones home nowhere once built. Standalone Headroom has a
**default-on telemetry beacon** (`HEADROOM_BEACON=off` to disable) and a
**HF model download** for Kompress (`HF_HUB_OFFLINE=1` + pre-pull, or
`HF_ENDPOINT` to a mirror). Both are documented, both are settable in compose
env — but the defaults are *online*, which cuts against Cove's offline-first
charter unless explicitly pinned. Slight edge to A on defaults; full parity is
achievable in B with two env vars. Also relevant: Headroom's Python-side dollar
pricing uses LiteLLM and needs Python 3.13 — a known versioning wrinkle.

**Latency & prompt-cache (favors B, correcting a July estimate).** The July
musing estimated Headroom at ~100-200ms/call. Upstream now claims **sub-ms** —
0.21ms p50 on 10K-token JSON, 1.4ms at 100K tokens, Rust core
(`benchmarks/bench_latency.py`). Live-zone compression keeps the frozen prefix
byte-identical so provider KV-cache survives; CacheAligner flags (never
rewrites) volatile content. The earlier "~85% vs ~90% cache hit" worry maps to
the *sidecar* integration; standalone's `--mode cache` is built to preserve the
prefix. B is the lower-latency, cache-safer deployment — and the latency number
the July musing anchored on is stale.

**Output-token reduction & agent leverage (favors B, decisively).** Input
compression is half the bill. Output shaping (verbosity steering, effort
routing) plus cross-agent memory plus `headroom learn` plus CCR retrieve are
capabilities LiteLLM does not have and the sidecar path does not expose. If
Cove runs one LLM-adjacent service, B is materially the more useful one.

**Test/coverage investment (favors A, weakly).** `cli/tests/test_litellm.py`
exists and has real drift debt. But the debt is against LiteLLM's *posture*,
not its existence, and the coverage-matrix entry is for the *profile*, which
could name headroom instead. The investment is in the *pattern* (optional LLM
proxy service), which B preserves — it is in the *implementation*, which B
replaces.

## The honest tension

This genuinely could go either way, and the deciding input is off-repo. If the
operator's real agents call `litellm.cove` by alias, A wins on continuity. If
not — if litellm.cove is configured-but-unused infrastructure, and the agents
that matter (opencode, Claude Code via `wrap`) would get more from memory +
output shaping + CCR than from an unused alias table — then B is the better
architecture *and* the safer carry. Given what is actually in this repo, the
evidence leans B, with low confidence because of the off-repo unknown.

I am not recommending "delete LiteLLM this week." I am recommending: adopt
standalone Headroom as Cove's agent-facing LLM service, evaluate it live
against litellm.cove for one cycle, and retire LiteLLM only after confirming no
harness calls it. That is Option B as a *migration*, not a rip-and-replace —
which is the only responsible reading of B given the off-repo alias uncertainty.

## What I searched (anti-rationalization disclosure)

Three progressively deeper, differently-framed probes into the load-bearing
absence claim ("Headroom standalone can't do Cove's per-model aliasing to a
custom Ollama-Cloud upstream"):

1. **Direct feature framing** — `headroom proxy OPENAI_TARGET_API_URL custom
   openai-compatible upstream ollama`. Found the endpoint-level knobs
   (`OPENAI_TARGET_API_URL`, `--openai-api-url`, Settings→Endpoints, per-request
   `x-headroom-base-url`) and Issue #1533 (custom endpoint classification).
   Confirmed endpoint-level routing exists; aliasing absent.
2. **Exact-stack framing** — `"headroom" proxy "ollama cloud" OR
   "ollama.com/v1" custom base url provider routing`. **Zero results** — no one
   has published Headroom→Ollama-Cloud. Absence deepened.
3. **Mechanism framing** — `HEADROOM_MODEL_ROUTES custom backend anyllm
   OpenAI-compatible endpoint configuration`, then a fourth targeted probe
   `HEADROOM_MODEL_ROUTER_ENABLED HEADROOM_MODEL_ROUTES "cost-aware" per-model
   alias routing`. Found PR #1706: cost-aware model router, **Anthropic
   `/v1/messages` path only** — auto-routing by request shape, not a per-model
   alias→upstream table. The one knob that sounded like aliasing is not.

Conclusion stated with the searches on record: Headroom standalone does **not**
provide per-model-alias routing to an arbitrary OpenAI-compatible upstream
equivalent to LiteLLM's `model_list`. The closest it gets is one custom
OpenAI upstream (`OPENAI_TARGET_API_URL`) serving all openai-compatible
traffic, plus an Anthropic-only cost router. After three differently-framed
searches this absence holds.

## Note on a doc-vs-deployed discrepancy found in passing

`docs/services/litellm-proxy.md` and the failing tests in
`docs/tech-debt/litellm-test-drift.md` both describe an nginx **route
whitelist** (`/health`, `/v1/models`, `/v1/*`, 403 catch-all). The deployed
`compose/nginx/default.conf.j2:130-153` does **not** implement it — it proxies
all paths ("All paths are proxied — isolation is from the 127.0.0.1 port
binding, not route whitelisting. Admin UI is enabled with a master key."). The
"route whitelist" is doc-and-test-only. This is the litellm-test-drift debt
surfacing in the template itself, and it means Option A's "nginx whitelist"
asset is currently unrealized — strengthening the case that A's hardening story
is aspirational where the musing assumed it was deployed.

## Certified Recommendation

**Option:** B

**Confidence:** low

**Key evidence:**
- Headroom standalone routes per-endpoint, not per-model-alias; its only model
  router (PR #1706) is Anthropic-path-only cost routing — cannot replicate
  `compose/litellm/config.yaml.j2`'s four Ollama-Cloud aliases without a
  reimplementation (CHANGELOG #1706; headroomlabs-ai.github.io/headroom/configuration/; searched 3 frames, §above).
- **Zero in-repo consumers** of the litellm.cove aliases (repo-wide grep for
  `litellm.cove` / `ollama.com/v1` / the alias names across json/ts/py/md → no
  harness binding; `2026-08-28-pullfrog-forgejo-adaptation.md` only *proposes*
  litellm.cove as a future PR-Agent endpoint) — the alias layer A would
  preserve is dormant in-repo.
- OpenCode integration is **shipped, not proposed**: Issue #76 closed,
  `plugins/opencode/` + `HeadroomPlugin` exist, `headroom wrap opencode` is a
  first-class supported target (github.com/headroomlabs-ai/headroom/issues/76;
  docs.headroomlabs.ai/docs/opencode).
- Security delta favors B on **velocity + realized supply-chain hit**: LiteLLM
  advisories still landing ~monthly (latest GHSA-3cv6-jpf6-8222, SSRF +
  credential exfil, 2026-08-26) on top of the March 2026 TeamPCP CI compromise;
  Headroom shows one security entry but adds CompressionAttack + plugin-priv
  (CVE-2026-32920 / GHSA-ff98-w8hj-qrxf) — acceptable under Cove's
  trusted-operator threat model per `docs/musings/litellm-headroom-context-proxy.md`'s own table.
- B adds platform capability A structurally lacks: output-token shaping,
  cross-agent memory, MCP tools, CCR retrieve, `headroom learn` (Headroom
  README) — and sub-ms latency (0.21ms p50) vs the stale 100-200ms July
  estimate (benchmarks/bench_latency.py).

**Reversibility:** High, because B is a *migration* not a deletion. Concretely:
bring up Headroom as a new optional compose profile (`headroom.cove`, same
variable-upstream nginx pattern as litellm), set `HEADROOM_BEACON=off`,
pre-pull Kompress, env-credentials via `cove creds`. Run it beside litellm.cove
for one cycle. Point opencode at it via `headroom wrap opencode`. Only after
confirming (out-of-repo) that no harness calls `litellm.cove/v1` by alias, run
`cove litellm down` and retire the profile. Full rollback = leave the litellm
profile intact throughout; it is never deleted until B is proven.

**Dissent recorded:**
- If the operator's out-of-repo agents DO call litellm.cove by alias
  (`deepseek-v4-flash` etc.), B as stated breaks them; that single fact would
  flip this to A. The repo cannot see that usage — operator must confirm before
  retiring the litellm profile.
- Headroom's defaults are **online** (telemetry beacon on by default, HF model
  download on first start). Offline-first parity requires explicit
  `HEADROOM_BEACON=off` + pre-pulled model in compose — one omit and Cove
  phones home. A's defaults carry no equivalent.
- The CompressionAttack vector has **no CVE yet** and no upstream fix — it is
  mitigated by threat model (self-injection is not a threat) not by code. If
  Cove ever processes attacker-controlled prompts through the proxy (e.g. the
  pullfrog steward reading PR text), CompressionAttack goes live and B inherits
  a risk A does not have.
- LiteLLM's hardening debt is *fixable in place* (`litellm-test-drift.md`,
  `cove-litellm-compose-profile-flag.md` are both small, well-scoped fixes);
  B's appeal rests partly on not having to do that work, which is a weak reason
  to replace rather than repair.
- The nginx route-whitelist discrepancy (docs/tests claim it; the deployed
  template proxies all paths) means A's current security posture is weaker than
  documented — but that same drift exists to be fixed, and fixing it strengthens
  A without any replacement.
