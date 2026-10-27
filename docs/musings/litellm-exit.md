---
title: "LiteLLM exit from Cove — incident-driven exit design"
created: 2026-10-26
status: Draft
---

# LiteLLM exit from Cove — incident-driven exit design

The operator's decision: Cove is replacing LiteLLM. Trigger: LiteLLM's own security-incident disclosure of the compromised v1.107.0 release ([attack-chain RCA, 2026-10-23](https://docs.litellm.ai/blog/security-incident-oct-21-2026-attack-chain)) — "they keep committing own-goals at an unacceptable rate." This musing is the **design of the exit**, not the exit. Nothing here has been implemented; no compose, CLI, nginx, or container state has been touched.

## The incident, in three lines

- A LiteLLM internal master key was committed to a public repo on 2026-05-27 and never revoked; on 2026-10-10 an attacker used it to reach the internal "Agent Platform" API and extract a GitHub org owner's CLI token, then exfiltrated more maintainer tokens through throwaway CI workflows.
- On 2026-10-21 the attacker repointed LiteLLM's release pipeline at a lookalike fork (`Berri-AI/litellm`), bypassed branch protection with the owner token, had the production gate approved with a stolen maintainer token, and published malicious `litellm==1.107.0` wheels to PyPI and Docker images (`v1.107.0`, `latest`, `main-latest`, `main-stable`) — a credential-stealing payload that harvests provider keys, SSH/GPG keys, browser data, and AI-tool auth files.
- The artifacts were live roughly two hours (PyPI quarantined by 13:23 UTC, Docker cleaned by 14:20 UTC); the last safe line is 1.106.2, and remediation releases (1.103.8 / 1.104.6 / 1.105.4 / 1.106.3) removed the eMudhra root CA from LiteLLM's trust bundles and rotated the cosign signing key.

## Exposure verdict: not affected, by pin construction

Cove pins `litellm[proxy]==1.84.0` in `compose/litellm/Dockerfile` (multi-stage build from `python:3.13-slim`, local image `cove-litellm:1.84.0`). The compromised artifact was exactly `1.107.0`; the affected Docker tags were the moving ones (`latest`, `main-*`), none of which Cove consumes. Even a rebuild during the two-hour window would have installed the pinned 1.84.0 from PyPI, which was untouched. So: **no interim pin bump is warranted, and none is proposed.**

Two residual notes, stated plainly and without alarm:

- The eMudhra root CA (compromised per Mozilla's 2026-10-17/20 disclosure, a separate incident) sat in the Debian/certifi CA bundles inside nearly every container image until distro and certifi updates landed — including `cove-litellm:1.84.0` and every other Cove image. That is a base-image hygiene matter fixed by rebuilding images after a CA-bundle refresh, not a LiteLLM-specific defect, and Cove's upstream provider chains do not cross eMudhra.
- The real residual risk is not this incident's payload — it is that Cove's per-version pin discipline cannot protect against the vendor's own release pipeline being the attack surface. That is precisely the class of failure this incident demonstrated twice (TeamPCP in March 2026 via the CI Trivy action; this one in October). The exit rationale rests on the drumbeat plus supply-chain trust, not on Cove having run a bad artifact.

Realistic blast radius had Cove been affected: the proxy is bound to `127.0.0.1:4000` inside the Docker network, fronted by nginx at `litellm.cove.local` on the LAN only, single-user, with the master key in 1Password/Vault and provider keys in a `0600` env file. A compromised proxy process would have had access to provider API keys and everything the proxy process could read — bad, but LAN-contained and credential-scoped. Neither alarmist nor dismissive: the shape of the deployment bounded it; the vendor's pipeline is what failed.

## What actually uses litellm.cove today

- The workstation's OpenCode provider config defines one provider pointed at `https://litellm.cove/v1` (`@ai-sdk/openai-compatible`), with model ids `nonstreaming:text:light`, `nonstreaming:text:standard`, `syn:large:text`, and `infinite:small:vision` — and the bb model-preference spokes reference ids in the `vision:heavy` family, which resolve through the same proxy. In practice, **bb-spawned coding agents are the traffic**.
- nginx access-log evidence over the container's retained window: roughly 19,300 `POST /v1/chat/completions`, client user-agent `opencode/latest/2.1.1/acp`, with multi-megabyte buffered request bodies and streamed responses — i.e., live agent chat traffic, not health-check noise (`GET /v1/models`: 3; `/health`: 28).
- The server-side ladder (operator-owned `${COVE_DATA_ROOT}/litellm/config.local.yaml`): 9 tier aliases across 21 deployments — `text:light` (3), `text:standard` (3), `text:ultra-heavy` (3), `vision:heavy` (3), `vision:super-ultra-heavy` (3), `nonstreaming:text:light` (2), `nonstreaming:text:standard` (2), `syn:large:text` (1), `infinite:small:vision` (1). Providers: Synthetic subscription (order 1 — spend this first), ollama-cloud metered credits (order 2), Synthetic backstop (order 3). No `fallbacks` list by design; the ordered deployments under each alias **are** the ladder.
- Streaming is real and depended on (nginx sends with buffering disabled and 3600-second timeouts specifically for this). Failover is LiteLLM's router moving to the next deployment on failure.
- This resolves the open question left by the September 8 headroom-vs-LiteLLM musing, which found "zero in-repo consumers" and leaned toward retirement on that basis at low confidence: the consumers were always out-of-repo, and they are now proven, heavy, and load-bearing. The alias layer is not dormant.
- The model **tier policy itself** (ADR-008 and the ladder semantics) belongs to the workstation lane (thread `thr_eqqq6bmzug`); this design reports the dependency and does not touch that config.

## The Cove-side surface an exit must remove or replace

| Area | Items |
|---|---|
| compose (main) | `litellm` service (profile `litellm`, build context `./litellm`, 127.0.0.1:4000, env_file + `LITELLM_MASTER_KEY`/`OLLAMA_API_KEY`/`DATABASE_URL`/`UI_USERNAME`/`UI_PASSWORD`/`PROXY_BASE_URL`/`STORE_MODEL_IN_DB`), `litellm-db` (postgres:16-alpine, profile `litellm`, pgdata bind), `headroom` (profile `litellm`, 127.0.0.1:4001, digest-pinned `chopratejas/headroom`) |
| compose (standalone) | `compose/litellm/` — `docker-compose.yml` (project `cove-litellm`: litellm + headroom, no db), `Dockerfile` (the 1.84.0 pin), `config.base.yaml` (hardening defaults + `headroom_settings` sidecar coupling, fail-open `fallback: direct`), `config_overlay.py` (the merge/credential-validation engine) |
| nginx | `litellm.cove` / `litellm.cove.local` server block in `default.conf.j2` (variable upstream, resolver, 3600s timeouts, buffering off), landing-page card + status dot (`landing.html`), test-only route-whitelist assertions |
| CLI | `cove litellm up/down/status/logs` (`cli/cove/litellm.py`: 1Password seeding of the shared "LiteLLM Proxy" item, master-key resolution, `.env` upsert, admin-identity injection from the shared Cove Admin item), `cove status` container tuples (cove-litellm, cove-headroom), `cove up --all` credential step + running-profile detection |
| bringup | cert SANs for `litellm.cove`/`litellm.cove.local`, `/etc/hosts` line, litellm data-directory task, `config_overlay.py` runtime-render invocation, `.env` template LITELLM_* vars |
| tests | `cli/tests/test_litellm.py` (121 tests, incl. the one `live`+`e2e`+`staging`-marked test), plus incidental refs in `test_cli.py` (`up --all`), `test_compose_source_guards.py`, `test_pins.py`, `test_staging_isolation.py`, `test_toolhive.py` (the MCP-guard guard), staging scripts' profile lists (`scripts/staging/*.sh`), `compose/docker-compose.staging.yml` |
| docs | `docs/services/litellm-proxy.md` (the reference service doc), litellm rows/sections in `docs/guides/stack-update-guide.md` (pin table, SBOM process, upgrade-procedure origin), AGENTS.md service note, README/CHANGELOG mentions, `docs/test-coverage-matrix.yaml`, tech-debt notes (`litellm-test-drift.md`, `cove-litellm-compose-profile-flag.md`), the litellm musings/plans corpus (historical, keep) |
| SBOM | `sbom/litellm.cdx.json`, `sbom/litellm-db.cdx.json`, `sbom/headroom.cdx.json` — dropped at the next release that removes the services (replace with the replacement's entry if any) |
| data + credentials | `${COVE_DATA_ROOT}/litellm/`: `pgdata/` (~288 MB — LiteLLM's postgres: request logs, UI state, DB-stored config under `STORE_MODEL_IN_DB=True`), `local.env` (provider API keys, `0600`), `config.local.yaml` (the operator's ladder — the only machine-local copy), `config.yaml` (generated), assorted migration backups; 1Password item "LiteLLM Proxy" (master key) and its Vault cache entries. The shared "Cove Admin" item stays (ADR-017, used by other services) |
| workstation coupling | **Operator ruling, 2026-10-26 (verbatim): "cove shouldn't hold ollama keys itself, those belong to" the workstation lane (thread `thr_eqqq6bmzug`).** Verified today: Cove's IaC and wheel hold no ollama key material; the only copy on Cove's disk is the pass-through `OLLAMA_API_KEY` in the deployed compose `.env`, projected by the workstation's SOPS role (issues #76/#78 history) and consumed by the litellm compose service. Cutover requirement: the replacement gateway receives the ollama-cloud key via workstation-lane provisioning directly into the replacement's own env — no new Cove-side custody, no Cove-managed secret store for it — and Cove's deployed `.env` drops the `OLLAMA_API_KEY` pass-through at teardown. The orchestrator is informing the workstation lane of the ruling directly |

Known pre-existing debt inside this surface (worth recording because the exit retires it rather than fixes it): the test-drift note (nginx route whitelist asserted by ~9 failing tests but not implemented in the template — docs-and-tests encode a stricter posture than deployed), and `cove litellm up` still passing `--profile` to Docker Compose v5, which removed that flag (workaround `COMPOSE_PROFILES=litellm` documented in the tech-debt note).

## Replacement candidates

Security track record is the top criterion — that is the reason for the exit — then IaC fit, then capability fit for a single-operator LAN.

| Candidate | Gains | Loses / risks | Postgres question | Migration shape |
|---|---|---|---|---|
| (a) No proxy — clients hit providers directly | Removes the third-party gateway supply chain entirely; one less CVE stream, one less pipeline to trust; provider keys already exist in the workstation config for direct providers | Ordered cross-provider ladder (Synthetic-first spend control, metered ollama-cloud second) has no client-side equivalent in OpenCode — tier ids and failover semantics die or move to the workstation lane by hand; provider keys scatter into every client config on every machine (worse for the leak class that caused all this); no compression (measured at only ~6.3% on real tool traffic — small loss) | litellm-db dies; its function (request/spend logging, UI state, DB-stored config) is replaced by nginx access logs + provider-native dashboards; nothing needed | Per-client provider blocks in the workstation opencode config; tier policy lane re-homes the ladder semantics as documented convention, not enforcement |
| (b) Headroom standalone (decouples cleanly) | Same lineage as the current sidecar; shipped OpenCode integration (`headroom wrap opencode`); output shaping, memory, MCP tools; sub-ms claimed latency | Cannot do per-model-alias routing to arbitrary OpenAI-compatible upstreams (verified by the three-frame search in the K3 musing — endpoint-level only, its one model router is Anthropic-path-only); the 9-alias/21-deployment ladder cannot be expressed; defaults phone home (beacon + HF pull) needing explicit offline pins; sidecar's fail-open compression becomes the whole service | litellm-db dies, nothing replaces it; headroom is stateless for this use | New `headroom` profile + nginx block; clients re-point; ladder lost |
| (c) Bifrost (maximhq) | Go, Apache-2.0, active; OpenAI-compatible `/v1` + provider/model aliasing that fits the tier ids; config.json-declared configuration with a local SQLite runtime store (`source_of_truth: "config.json"`, restart-based — governance requires a store; pure file-only mode cannot carry routing rules) is genuinely IaC-native; credentials via env refs; documented OpenCode integration; ordered fallback ladders verified by the 2026-10-26 spike (see ladder-fit section); thin-but-real advisory ledger with fast fixes (2 advisories at the Sep 8 evaluation; a third since — see below) | Ledger grew Sep 23: CVE-2026-90898 (critical) — unauthenticated RCE via MCP stdio client registration when management auth is disabled, the default; all three advisories share one root pattern (default-insecure management plane) and are all closed by the same controls Cove would apply anyway (static official image, auth enabled in config, localhost bind behind nginx); Ollama-cloud streaming auth re-verified working in the 2026-10-26 spike; VC-backed with enterprise tilt | litellm-db dies; Bifrost needs only a local SQLite runtime store seeded from config.json — spend/usage visibility moves to provider dashboards, the gateway's own request log, and nginx logs | New `bifrost` profile: digest-pinned static image, `config.json` mirroring the 9 aliases/ordered deployments, env-ref credentials (Synthetic through the Cove creds pattern; the ollama-cloud key provisioned by the workstation lane directly into the replacement's env per the 2026-10-26 ruling), nginx variable-upstream block at `bifrost.cove`, clients re-point with model ids preserved |
| (d) Minimal nginx auth+route layer | No new software; nginx already fronts everything | nginx is a router, not a gateway: no retries/failover, no alias ladder, no per-model semantics; putting provider keys into nginx config/templates spreads secrets wider; false economy | litellm-db dies; logging stays nginx-only | Not viable as a ladder replacement; only sensible as a hardening layer for (a) |
| (e) Envoy AI Gateway / Higress (CNCF-grade gateways) | Clean-ish records, CNCF governance, real gateways | Built for k8s/Envoy/Istio control planes — heavy ops burden on a single-host compose LAN box for a one-operator problem; capability far beyond need | litellm-db dies; each brings its own control-plane state | Rejected on ops-burden proportionality, not security |

## Recommendation

**Adopt Bifrost as the replacement gateway, staged additively.** Operator ruling, 2026-10-26: "no-proxy is not a good choice" — option (a) is dropped from consideration, and both Bifrost spike gates were run the same day and passed (see the ladder-fit section). Rationale:

- The named contingency has fired. The Sep 8 triple-depth evaluation concluded: "Bifrost stays the named contingency if LiteLLM supply chain degrades further — its activation trigger is a LiteLLM event (new critical CVE or compromise), not a Bifrost event." Two supply-chain compromises in seven months, the second shipping malware through the vendor's own signed pipeline, is that event.
- It is the only candidate that preserves what is actually used: the 9-alias tier ladder with ordered deployments, OpenAI-compatible streaming, and client model ids — behind an IaC-native file config that fits Cove's compose + creds pattern. The workstation lane's tier policy survives intact except for the base URL.
- Its security ledger is honest: three advisories, all fixed promptly, all requiring a default-insecure management plane that Cove's deployment shape (auth enabled in `config.json`, static digest-pinned image, localhost bind, nginx in front) closes passively. That is a better posture than LiteLLM's (16+ CVEs, ~monthly drumbeat, two supply-chain compromises) — while being candid that "default-insecure management plane, three times" is a pattern to watch, and Bifrost would go onto the same 48–72-hour-hold vendor-update discipline as everything else.
- "No proxy" is the more radical and in some ways more principled answer — zero gateway supply chain — but it breaks the ladder's spend-control semantics (Synthetic-first, metered-second), scatters provider keys across client machines, and pushes enforcement into documentation. If the operator values supply-chain minimalism over ladder enforcement, (a) is the coherent choice; it is a workstation-lane-led project more than a Cove one.

Not recommended: Headroom standalone as the router (cannot express the ladder; compression's measured value is ~6.3% on real traffic), nginx-only routing (no gateway semantics), and the CNCF-heavy gateways (disproportionate ops burden).

## Ladder fit: can Bifrost express the ordered tier ladder?

Asked directly, and answered against today's docs rather than the September snapshot, because this is the load-bearing claim behind the recommendation.

- **The ladder's semantics map 1:1 onto Bifrost's core engine.** LiteLLM's "ordered deployments per alias, try the lowest healthy order first" is exactly Bifrost's fallback chain: each hop is tried in order, each hop gets its own full retry budget, first success wins, and the response's `routing_info` records which hop served (strictly better failover observability than today). Synthetic-first spend ordering is preserved by chain order, not weights.
- **Both upstreams express as custom OpenAI-compatible provider instances.** `custom_provider_config` with `base_provider_type: "openai"`, per-instance `base_url`, request-path overrides, and `env.*` key references matches Cove's credential pattern exactly; multiple instances of an OpenAI-compatible provider have been supported since the custom-provider-instances issue closed in August 2025.
- **One quirk is handled better than today.** Per-instance `allowed_requests` can make the infinite backstop instance streaming-only, so non-streaming traffic structurally cannot reach the endpoint that 400s on it — LiteLLM could only express this by dropping the order-3 hop from the nonstreaming aliases.
- **One shape change, absorbed server-side.** LiteLLM hides provider and slug behind the bare tier id; Bifrost addresses `provider/model` and carries chains as ordered fallbacks. The server-side home is a routing rule: a CEL expression matching the bare model, a primary target, and an ordered fallback list — the mechanism that keeps client-facing tier ids unchanged.
- **One failure-class nuance to design around:** a `400` (`caller_fault`) does not cascade a rule-provided fallback chain. Harmless for Cove — the 400-happy infinite endpoint is the last hop and the nonstreaming tiers already drop it — but it belongs in the ladder-translation notes so nobody is surprised by it later.

### Gate results (spike run 2026-10-26, both green)

The two gates were run as an isolated spike (separate containers on ephemeral ports, a mock OpenAI upstream, no Cove stack involvement, no Cove compose changes; the ollama-cloud key passed via an env file from the workstation-projected pass-through, never printed, and every spike copy deleted afterward). Evidence: the spike config JSONs and mock harness live in the session's temp spike directory; results below are reproducible from them.

- **Gate 1 — server-side ordered ladder with bare tier ids: PASS.** A routing rule (`cel_expression: "model == 'text:standard'"`, primary target `mock-a/hf:fake/model-a`, ordered fallback `mock-b/hf:fake/model-b`) produced: primary healthy → primary serves with no fallback; primary 500 → fallback serves with `is_fallback: true`, per-hop model slugs differing exactly as the ladder needs; streaming through the fallback returns normal SSE with per-chunk `routing_info`; recovery of the primary returns traffic to it. Client-facing `requested_model` stayed `text:standard` end to end.
- **Gate 2 — ollama-cloud streaming auth: PASS.** Through a custom OpenAI-compatible provider instance (`base_url https://ollama.com`, env-ref key), a non-streaming control returned 200 and a streaming request returned 200 with 18 SSE chunks and a clean `[DONE]` — no Authorization-header omission on the streaming path in this release.
- **Operational findings the implementation must carry:**
  - Pure file-only mode (`config_store.enabled: false`) cannot carry governance: the bootstrap refuses ("config store is required"). The working shape is `config.json` + a local SQLite runtime store with `source_of_truth: "config.json"` — still declarative and restart-based, but the store is a required runtime artifact, and its file must pre-exist at the configured path (the default logs store auto-creates; the config store does not).
  - Docs bug found and worked around: the governance config page's example CEL (`request.model == 'gpt-4o'`) does not compile — `request` is a numeric rate-limit variable; the routing-rules page's `model == '…'` is the correct form.
  - For custom OpenAI-compatible providers, `base_url` must exclude `/v1` (Bifrost appends `/v1/chat/completions`; passing `…/v1` yields `/v1/v1/...` 404s).
  - A file-seeded virtual key did not authenticate while an API-created key did — VK auth needs a re-check in the implementation sashay; the production shape may want VKs minted via the management API (values via `env.` refs) rather than seeded from the file.
  - Inference authentication is enforced by default in this release (a missing VK is a 401) — the posture the exit plan wants, obtained for free.

## Rugpull risk: could the replacement do a LiteLLM?

The candidates table scores Bifrost's CVE ledger and records its enterprise tilt, but the question that actually killed LiteLLM deserves its own answer: what happens if the replacement's release pipeline is compromised the same way, or the vendor gates the OSS core away?

- **What failed at LiteLLM was org compromise, not a code bug.** An owner token bypassed branch protection, a stolen maintainer token approved the gate, and a *signed* malicious release shipped. No consumer-side pinning defends against that; digest pinning and holding periods only bound the damage after the fact. This also caps how much weight Bifrost's documented supply-chain posture can carry: their security page advertises 100% GitHub Actions SHA-pinning, npm provenance, and CI dependency pinning, but the LiteLLM RCA is itself the proof that action-pinning does not stop an org-compromise attack.
- **Bifrost's exposure to the same class is real but smaller on every axis that matters to Cove.** Same GitHub org model (Maxim AI, VC-backed, with an enterprise repo beside the OSS one), and the same management-plane mistake pattern three times in six weeks — so the "vendor hygiene" reason for leaving LiteLLM is a watch-item, not a solved problem, at Bifrost too. What actually shrinks Cove's exposure: the artifact Cove would deploy is one statically linked Go image pulled by digest — no PyPI wheel path (the exact artifact class that was poisoned), no Python/prisma dependency tree, no bundled postgres. The trusted-party set shrinks from "package registry + pipeline + runtime + DB + UI" to "one digest-pinned binary plus a local SQLite runtime store."
- **What binds regardless of vendor** is already in the exit plan: digest pinning, the 48–72-hour hold plus the freeze policy, an SBOM delta at every bump, localhost + nginx-only exposure, provider keys in a `0600` env file scoping any compromised process to what it can read, and nginx access logs plus provider-side spend dashboards as the tripwires that would catch a rogue binary exfiltrating. At implementation time, check whether Bifrost publishes image signatures/provenance and, if so, verify them in bringup rather than trusting the digest alone.
- **The honest limit:** the exit lowers probability and shrinks the trusted set; it does not change the impact class. A malicious gateway binary sees the same provider keys and the same traffic a malicious LiteLLM would have seen. (Candidate (a), no proxy, was the only option that removed the class entirely; the operator ruled it out on 2026-10-26.) The pre-agreed escalation: a LiteLLM-class event at Bifrost (pipeline compromise, abandonment, or OSS-core gating) triggers a re-run of the candidate evaluation — with (a) ruled out, the fallback is the next-best evaluated candidate rather than client-direct. The evaluation in this musing makes that second exit a decision, not a project.
- **Insurance already written:** the teardown order, drain window, client re-pointing, and data-disposal steps in the exit plan below are vendor-agnostic. This document doubles as the generic "how Cove leaves any gateway" playbook, which is the piece that was missing when the LiteLLM exit became urgent.

## Rugpull risk, the other kind: license change and open-core gating

The first rugpull section covers a compromised pipeline; this one covers the quieter version — the vendor starts charging for what was free, or splits the useful parts into a paid tier.

- **Bifrost has already made the split, and the split's location is the good news.** The OSS core (Apache-2.0, held by the vendor's legal entity) keeps exactly what Cove needs: routing, automatic failover, provider/model aliasing, virtual keys, basic budgets, semantic caching, the MCP gateway, observability, and even the prompt/response request log. What sits in the separately licensed Enterprise tier today is the list Cove does not use: clustering, adaptive load balancing, SSO/SAML/SCIM, RBAC, audit logs, guardrails, hierarchical budgets with alerting, log exports, secret-manager integrations, and in-VPC/air-gapped support packaging. No published enterprise pricing, which is itself a watch-item.
- **The realistic gating vector misses Cove.** What vendors gate is what enterprises pay for — identity, governance, audit, scale. Cove's need is the commodity core (OpenAI-compatible routing, an alias ladder, streaming), which is every gateway's marketing table-stakes and the least profitable thing to gate. LiteLLM itself was already traveling this exact road (enterprise SSO/audit tier) — the difference is its supply-chain failures forced the exit before the pricing ones could.
- **The mitigant is the license plus the shape of the deployment.** Apache-2.0 grants fork rights, and Cove's proposed shape (file-only config, digest-pinned image, no DB) means the last Apache-tagged release keeps working as a stateless router for a long time; a frozen router ages slowly. Config portability bounds the switching cost: the whole ladder is nine aliases in one small file, roughly a day to re-express in any successor.
- **Ranking on this axis** (recorded for completeness; no-proxy was ruled out on 2026-10-26): no-proxy (nothing to relicense) would beat the CNCF-governed gateways (a foundation cannot unilaterally relicense; strongest governance in the field, rejected on ops burden alone), which beat nginx (BSD-2, stable under F5 for two decades), which beats Bifrost and Headroom (permissive today, VC-backed with a paid tier beside the OSS repo — medium risk, mitigated as above). Watch trigger: any license-file change, pricing-page appearance, or move of an OSS-core feature into the enterprise tier goes to the operator under the same escalation as the supply-chain trigger.

## Data sovereignty

The gateway choice changes who holds copies of the traffic and what phones home; it never changes the upstream, which is the part sovereignty talk often blurs.

- **The upstream is unchanged under every candidate.** Prompts already leave the LAN for US-hosted providers (Synthetic, ollama-cloud) the moment any proxy or client forwards them. No gateway choice repatriates that; the honest sovereignty deltas are copies at rest, vendor telemetry, and the management plane.
- **Copies at rest are today's debt.** LiteLLM's Postgres accumulated roughly 288 MB of request logs on Cove's disk — prompt metadata and possibly bodies — which the exit's disposal step handles. The lesson becomes an adoption gate for the replacement: request-body logging off or metadata-only by default, declared in IaC, with a short retention if logs stay on. Bifrost's OSS request log is body-capable, so this gate is not hypothetical.
- **Phone-home posture diverges sharply.** LiteLLM 1.84.0 as deployed phones home nowhere once built. Headroom standalone defaults ON (telemetry beacon plus an HF model pull; explicit offline pins required, documented in the K3 musing). Bifrost shows no evidence of vendor telemetry — its telemetry docs cover Prometheus/OpenTelemetry export the operator configures, and its FAQ asserts self-hosted deployments never pass through vendor servers — but that is vendor-asserted, so the implementation sashay verifies it with a zero-egress check rather than trusting the claim.
- **Enforcement beats verification where Cove can have it.** The gateway container needs egress only to the two upstream providers; Cove's offline-first charter justifies an egress allowlist (Docker network policy or the existing dnsmasq resolver as the choke point) so a future release cannot quietly grow a telemetry endpoint. Recommended as part of the replacement's compose profile.
- **Ranking on this axis** (recorded for completeness; no-proxy was ruled out on 2026-10-26): no-proxy (fewest copies: traffic exists only on the client and at the provider) would lead; the current LiteLLM deployment and a hardened Bifrost profile (logs off, egress allowlisted) are comparable; Headroom standalone trails until its beacon is pinned off and its cross-agent memory store is accepted as a new prompt-derived store on disk; the CNCF candidates are clean by default but rejected on ops burden as before.

## Exit plan (removal order, once the replacement is chosen)

1. **Coordinate with the workstation lane** (`thr_eqqq6bmzug`) before any Cove change lands: client re-pointing (`opencode.json` provider base URL), model-id continuity, and the ollama-cloud key handoff — workstation-lane property per the 2026-10-26 ruling, so the lane provisions the key directly into the replacement's env while Cove's `.env` pass-through is dropped at teardown; the orchestrator has informed the lane directly. bb-side model-preference spokes that name proxy-resolved ids update in the same motion.
2. **Deploy the replacement additively** alongside LiteLLM (new profile + nginx block, e.g. `bifrost.cove`), port the ladder from `config.local.yaml` into the new config format, wire credentials through the existing `.env`/`cove creds` pattern, and verify with a real agent session (streaming, long tool-heavy context, failover by pulling order-1 credentials). The profile adopts with the sovereignty gates from the section above: request-body logging off or metadata-only, declared in IaC, plus an egress allowlist so the gateway container can reach only its providers.
3. **Re-point clients** in the workstation lane; watch the nginx access log for the old vhost until it reads zero agent traffic over an agreed drain window (a week is comfortable given ~19k requests/window).
4. **Remove the services** in one PR series: compose services (`litellm`, `litellm-db`, `headroom`) + the `litellm` profile; the standalone `compose/litellm/` resource directory including `config_overlay.py`; the `cove litellm` CLI group, `cove status` tuples, and the `cove up` credential step/profile detection; the nginx server block, landing card, and status dot; bringup cert SANs, `/etc/hosts` line, data-dir task, overlay-render task, and `.env` template vars.
5. **Tests in the same series**: retire `test_litellm.py` (or reduce to negative guards: profile absent, CLI command absent, nginx block absent, ToolHive's "Cove's only MCP surface" note updated); update `test_cli.py` (`up --all`), compose-source guards, pins inventory, staging scripts' profile lists, staging compose overlay, and the coverage matrix. This also closes, by deletion, the two open litellm tech-debt notes (test drift, Compose v5 profile flag) — record that in them before removing.
6. **Docs and SBOM**: delete `docs/services/litellm-proxy.md`; update the stack-update guide's pin table, SBOM process references, and upgrade-procedure provenance note (the 48–72h hold predates the exit and stays); update AGENTS.md/README; CHANGELOG entry; SBOM trio dropped (and the replacement's `sbom/` entry added) at the next release.
7. **Data and credential disposal — gated, irreversible, operator sign-off required** (this is the only destructive step, and it is separated in time from the code removal):
   - `${COVE_DATA_ROOT}/litellm/pgdata/` (~288 MB): request logs and possibly DB-stored config — may contain prompt metadata. Choose: secure-delete, or age-encrypt and archive under the existing encryption-at-rest policy, with a retention date.
   - `local.env` (the Synthetic-side provider credentials): migrate to the replacement's env first, then rotate — they lived in a LiteLLM-managed env and in the proxy's operational context; rotation after cutover is cheap hygiene. The ollama-cloud key is not re-homed by Cove at all: per the 2026-10-26 ruling it is workstation-lane property, provisioned by the lane directly into the replacement's env.
   - `config.local.yaml`: keep as reference until the replacement's ladder is verified, then archive or delete.
   - The deployed compose `.env` drops the `OLLAMA_API_KEY` pass-through line at teardown: workstation-lane property per the 2026-10-26 ruling, and the replacement has received the key directly from workstation provisioning by then.
   - 1Password "LiteLLM Proxy" item + its Vault cache entries: delete after the rollback window closes (keep one release, since a prior-wheel rollback would expect it).
8. **Status-check replacement**: `cove status` drops the two litellm tuples and gains the replacement's tuple (or nothing, under option (a)); the landing page card/dot follows the same substitution.

Rollback shape: the exit lands as a normal release; the prior release's wheel restores the whole surface, and the pgdata step is deferred until the rollback window closes — which is why it is gated separately.

## Interim risk note (until the exit lands)

- No Cove artifact is affected by this incident; no pin bump is proposed or needed.
- Recommend a **freeze on LiteLLM pin bumps** until the exit decision is executed — the vendor-update policy's 48–72-hour hold assumes a trustworthy pipeline, and the pipeline is the thing under question. The pin stays 1.84.0.
- One hygiene item independent of this incident: rebuild Cove's images after the base-image CA bundles finish removing the compromised eMudhra roots (applies to every image, not just litellm's).
- If LiteLLM's promised "process improvements" post (due the week after the RCA) materially restores trust, that is an input to the operator's replacement choice — not a reason to un-freeze bumps on the current pin.

## Open questions for the operator

1. **Replacement choice (narrowed by rulings)**: no-proxy was ruled out on 2026-10-26 and both Bifrost gates passed the same day — the remaining call is confirming Bifrost as the replacement, or holding until LiteLLM's process-improvements post lands this week.
2. **pgdata disposal**: secure-delete immediately at teardown, or age-encrypted archive with a retention date — and if archived, how long?
3. **Key rotation timing** (ownership is settled — the 2026-10-26 ruling assigns the ollama-cloud keys to the workstation lane; only timing remains open): rotate the Synthetic and ollama-cloud keys at cutover, or after the rollback window closes?
4. **1Password "LiteLLM Proxy" item**: delete at teardown, or keep one release for the rollback path?
5. **Drain window length** before service removal: one week proposed — acceptable, given the workstation lane controls the client re-point timing?

## Implementation findings (additive build, 2026-10-26)

The additive build is on a WIP draft PR: `cove bifrost` verb group, the
`bifrost` compose profile (digest-pinned v2.3.2 + a DNS-choke egress sink),
the nine-tier ladder as CEL routing rules with ordered fallback chains, the
pre-seeded SQLite config store, and the service doc
[docs/services/bifrost.md](../services/bifrost.md) — which now owns the
cutover checklist and the four pending operator decisions above. Findings
recorded at implementation:

- **File-seeded virtual key: spike finding resolved.** On transports v2.3.2
  the file-seeded VK authenticates (live-smoke proved 401-for-no-key and
  200-for-file-seeded-key on the same governance config). The `config.json`
  + pre-seeded store shape from the spike is adopted unchanged.
- **Signature/provenance: nothing to verify.** Upstream publishes no cosign
  signatures, no attestations, no image SBOM (release-pipeline.yml read
  2026-10-26). Anchors are the pinned digest + the 48-72h hold; recorded in
  the service doc, nothing wired into bringup verification.
- **Streaming-only gate: structural, verified.** The backstop instance's
  `allowed_requests` leaves only `chat_completion_stream` enabled; the live
  smoke shows a non-streaming request to the gated tier never reaches any
  upstream. The improvement over LiteLLM holds at runtime.
- **Cutover plan approved (2026-10-26).** The operator approved all four
  pending decisions above (pgdata: secure-delete; key rotation: at cutover,
  the ollama half scheduled by the workstation lane against the date cove
  sends; 1Password `LiteLLM Proxy` item: retained until the drain window
  closes, then deleted; drain window: one week) and adopted the
  product-neutral client endpoint `llmproxy.cove` (+ `.cove.local`) as the
  canonical client-facing surface — clients re-point there, and product
  swaps change the alias vhost's upstream variable only. The resolved
  two-phase cutover runbook lives in
  [docs/services/bifrost.md](../services/bifrost.md) ("Cutover checklist").
