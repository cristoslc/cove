---
title: "LiteLLM + Headroom as a Context Compression Proxy for OpenCode"
created: 2026-07-23
authored-by: deepseek-v4-flash:cloud
status: Draft
---

# LiteLLM + Headroom as a Context Compression Proxy for OpenCode

## Problem

DCP (Dynamic Context Pruning) works but has issues: it leaks into the model's thinking blocks, mucks up responses, and operates as a plugin inside the agent's awareness. The model sees the compress tool, sees pruning notifications, and sometimes confuses DCP's metadata with its own reasoning.

## The Landscape

Three approaches to context management for coding agents:

### 1. Plugin-based (DCP, context-mode)
Runs inside the agent's process. Hooks into message pipeline. Model is aware of compression — sees tools, notifications, placeholders. This awareness is the source of leakage.

### 2. Lossless Context Management (opencode-lcm, lossless-claw)
SQLite-backed DAG summarization. Preserves everything losslessly. Model gets retrieval tools (lcm_grep, lcm_expand). More sophisticated than DCP but still plugin-based — model is aware of the memory system.

### 3. Proxy-based (LiteLLM Headroom, Sleev)
Sits between agent and LLM provider. Compresses tool outputs, file reads, RAG payloads *before* they reach the model. The model never sees compression prompts, tool descriptions, or placeholders. It's transparent.

## Why Proxy-Based Is Interesting

The key insight: if compression happens at the proxy layer, the model has zero awareness of it. No thinking-block leakage. No "I notice you've compressed some context" confusion. The model just sees smaller inputs.

LiteLLM's Headroom feature:
- MIT-licensed (unlike Sleev which is proprietary SaaS)
- Runs as a proxy guardrail — one config switch
- AST-aware compression for code (preserves function signatures, collapses bodies)
- Works with any provider Anthropic, OpenAI, Bedrock, etc.
- No client changes — just point OpenCode at the proxy

## Fit for Cove

Cove is a local developer platform. A LiteLLM proxy with Headroom is a gateway service that coding agents route through. This fits Cove's model:

- **One service in the harbor** — compose file, environment config, done
- **Optional, not core** — if you don't use coding agents, you don't need it
- **Local-first, online-capable** — LiteLLM proxies to local Ollama with compression running locally, no internet needed. Same proxy also routes to Anthropic/OpenAI when online. One service, both modes.

## Open Questions

- How does Headroom interact with Anthropic's prompt caching? Compression changes message prefixes, which invalidates cache prefixes. LiteLLM claims ~85% cache hit rate vs ~90% without — acceptable tradeoff.
- Does Headroom support OpenCode's tool-call format? OpenCode uses OpenAI-compatible API format. LiteLLM proxies that natively. Should work.
- What's the latency overhead? Headroom uses a small model (Kompress-base) for compression decisions. Adds ~100-200ms per call.
- How does this compare to just using OpenCode's native compaction? Native compaction is lossy and model-aware. Headroom is lossy but transparent. The transparency is the differentiator.

## Security Landscape (July 2026)

Both projects have significant security findings. Understanding them is essential before adopting.

### LiteLLM — 16+ CVEs + Supply Chain Compromise

**Supply chain (March 2026):** TeamPCP backdoored PyPI releases via a compromised Trivy GitHub Action in LiteLLM's CI/CD pipeline. Stole PyPI credentials, published malicious `litellm` packages. Three-stage malware: downloader, injector, payload.

**Critical code CVEs (2026):**
- **CVE-2026-42271** (CVSS 8.8, CISA KEV) — Command injection in MCP test endpoints. Actively exploited in the wild.
- **CVE-2026-42208** — Unauthenticated SQL injection in API key verification path (fixed in 1.83.10).
- **CVE-2026-47101/47102/40217** (CVSS 9.9 chain) — Auth bypass → privilege escalation → RCE from default low-privilege user.
- **CVE-2026-49468** (CVSS 9.5) — Host header injection auth bypass (fixed in 1.84.0).
- **CVE-2026-42203** — SSTI in `/prompts/test` endpoint.
- **CVE-2026-35030** (critical) — JWT auth bypass (only if `enable_jwt_auth` is on).

### Headroom — Fewer, But Novel Attack Surface

- **CVE-2026-32920** — Automatic installation of untrusted plugins.
- **GHSA-ff98-w8hj-qrxf** — Plugins run with full system privileges.
- **CompressionAttack vector** (no CVE yet) — Adversarial compression: a benign-looking input transforms into malicious instructions after compression, giving the attacker control of the downstream LLM agent. Headroom's compression techniques make it susceptible.

## Can We Mitigate the Novel Risks?

The threat model for Cove is fundamentally different from a multi-tenant SaaS deployment. Cove is local-first, single-user, not internet-facing. This changes the calculus significantly.

### Supply Chain (LiteLLM)

**Still matters.** A poisoned dependency running locally has access to your API keys, source code, and filesystem. Mitigations:

- **Pin by hash** — `pip install litellm==1.84.0 --hash=sha256:...` in the compose build. No auto-pull of latest.
- **Vendor the dependency** — check the wheel into Cove's repo or a private registry. Eliminates PyPI as a live attack surface.
- **Minimal image** — don't run LiteLLM with unnecessary plugins or management endpoints enabled. Disable the UI, disable user management if not needed.
- **Read-only filesystem** — run the container with `--read-only` where possible.

### Network-Based CVEs (LiteLLM)

**Mostly neutralized by deployment model.** Cove runs LiteLLM as a local container, not exposed to the internet. No Host header injection is possible when the only caller is localhost. No unauthenticated SQL injection when the proxy isn't reachable from outside. The CISA KEV (CVE-2026-42271) requires an API key and network access — both absent in a local-only setup.

Mitigations:
- Bind to `127.0.0.1` only, not `0.0.0.0`
- Put a lightweight reverse proxy (Caddy, nginx) in front if any external access is needed
- Keep pinned to `>=1.84.0` for the cumulative fixes

### CompressionAttack (Headroom)

**This is the genuinely novel risk** — it doesn't exist without compression. An attacker crafts input that, after compression, becomes a prompt injection. In a multi-tenant proxy this is critical. In Cove's local setup:

- **The attacker is you.** You're the one crafting the prompts. Self-injection is not a threat.
- **But supply chain changes this.** If a compromised dependency or malicious plugin sends crafted input through the proxy, compression could amplify the attack. The compression layer becomes an unintentional adversary.
- **Mitigation:** Run Headroom's compression model locally (not a remote API). Pin the model hash. If the compression model itself is compromised, you have bigger problems.

### The Honest Assessment

For Cove's use case (local, single-user, trusted operator), the novel security risks are **manageable**:

| Risk | Severity (general) | Severity (Cove) | Mitigation |
|------|-------------------|-----------------|------------|
| Supply chain | Critical | High | Hash pinning, vendoring |
| Network CVEs | Critical | Low | Localhost-only binding |
| CompressionAttack | High | Low | Local model, trusted operator |
| Plugin abuse | High | Low | Don't install untrusted plugins |

The transparency benefit of proxy-based compression still outweighs the security overhead for Cove. The key discipline: **pin everything, vendor what you can, expose nothing to the network.**

## Headroom vs DCP: What the Community Says

There's no direct "Headroom vs DCP shootout" in the wild, but the contours are clear from scattered commentary.

### DCP (Dynamic Context Pruning)

- **Model-aware compression** — exposes a `compress` tool the model calls when it decides context is stale. The model sees placeholders, sees the tool, knows compression happened.
- **50-70% token reduction** on long sessions (per Upsun's deployment guide).
- **Plugin-based** — runs inside OpenCode's process. No proxy to manage.
- **Successor: Sleev** — DCP's README now recommends Sleev for new users: "Sleev is a local proxy for Claude Code, Codex, and OpenCode that builds on DCP's core ideas with newer context-management features." The project itself is migrating from plugin to proxy architecture.
- **Configurable thresholds** — `minContextLimit`, `maxContextLimit` for smaller local model windows.
- **Protected zones** — most recent 40K tokens are a "safety cushion" that cannot be touched.

### Headroom

- **Transparent proxy** — `headroom wrap opencode` routes all API calls through compression. The model has zero awareness.
- **20% fewer tokens for coding agents**, 60-95% for JSON payloads (per Headroom's own benchmarks).
- **Reversible compression (CCR)** — the model gets a `retrieve_headroom` tool to fetch originals when needed. This is the key differentiator from DCP's lossy placeholders.
- **AST-aware for code** — preserves function signatures, collapses bodies. Better than generic summarization for coding workloads.
- **LiteLLM native** — runs as a guardrail in LiteLLM's pre_call step. One config switch per virtual key.
- **Cross-agent memory** — Claude Code, Codex, and OpenCode can share the same compressed context store.

### Community Sentiment

- **Reddit (r/LLMDevs):** "Context compression is the real MVP" — but some users report not seeing the claimed savings. Headroom's own docs acknowledge this: "A/B test before assuming the 85% claim applies to your bill."
- **VibecodingHub review:** Headroom covers OpenCode as a supported target. The proxy path is recommended for minimal application changes.
- **Headroom GitHub Issue #76:** An OpenCode npm plugin (headroom-opencode) is proposed for deeper integration — auto-start proxy, expose compress/retrieve/stats as OpenCode tools, register as a compaction provider. Not built yet.
- **andrew.ooo review:** "Anthropic prompt caching is still better for fixed prefixes. Headroom shines when context is dynamic — tool outputs, RAG, logs." This maps directly to OpenCode's workload: heavy tool outputs, file reads, git diffs.
- **DCP's own trajectory toward proxy (Sleev)** validates the thesis. The plugin model has inherent limitations (model awareness, process coupling) that a proxy architecture solves.

### The Unanswered Question

No one has published a head-to-head: same OpenCode session, same task, same model — DCP vs Headroom proxy. The metrics that matter:

1. **Token savings** — DCP claims 50-70%, Headroom claims 20% for code. But DCP's savings include the compress tool's own overhead. Headroom's 20% is pure input reduction.
2. **Thinking-block cleanliness** — DCP leaks compression metadata into model reasoning. Headroom should eliminate this entirely. No one has measured this.
3. **Cache hit rate** — DCP invalidates provider caches when it prunes. Headroom's CacheAligner stabilizes dynamic content. LiteLLM claims ~85% cache hit rate with Headroom vs ~90% without.
4. **Latency** — DCP adds near-zero latency (it's a local string operation). Headroom adds ~100-200ms per call for the compression model.

The honest take: DCP is better for short sessions where latency matters. Headroom is better for long sessions where thinking-block leakage and cache invalidation dominate. The proxy approach also scales across agents (Claude Code, Codex, OpenCode all benefit from one proxy), which DCP cannot do.

## Next Steps

1. Set up LiteLLM proxy locally with Headroom enabled
2. Point OpenCode at it, run a long session
3. Compare token usage, response quality, and thinking-block cleanliness vs DCP
4. If it works well, add a Cove compose profile for it
