---
title: "LiteLLM Router Architecture: Multi-Provider Balancing with ZDR Constraints"
created: 2026-09-08
status: Draft
---

# LiteLLM Router Architecture: Multi-Provider Balancing with ZDR Constraints

Buildable design for the Cove router's config layer. Companion jam session (separate) covers the quality-aware auto-router, which is a custom hook, not config.

## Context

The eroding-subscription assumption (see [metered economics](./2026-09-08-custom-compressor-metered-economics.md)) changes the router's job. Today it routes four aliases to one paid upstream (Ollama Cloud metered). The new job: balance across three providers — **OpenCode Zen/Go (free tier + subscription), Synthetic (subscription with Always-On models), Ollama Cloud (metered)** — so that subscription and free quota are consumed before metered tokens are spent. Plus: the router must know which deployments carry current ZDR agreements and exclude stale ones for workloads that require it.

Verified provider facts (this session):
- **Synthetic** (`https://api.synthetic.new/v1`, OpenAI-compatible): Always-On models included in subscriptions — GLM-5.3-Flash, GLM-5.2, Kimi-K3 (`syn:large:vision`), Qwen3.8-27B, gpt-oss-120b, Nemotron-3-Super. `syn:` aliases auto-route to their latest recommended model (avoids 404s from model rotation). Operator key exists in opencode auth.
- **OpenCode Zen/Go** (`https://opencode.ai/zen/v1`, OpenAI-compatible): free tier (DeepSeek V4 Flash free, Big Pickle, MiMo-V2.5, Nemotron 3 Ultra, North Mini Code) plus Go subscription for curated open coding models. One key covers both. Anthropic-shape on a separate path. DeepSeek served under a **ZDR agreement renewed monthly (current through 2026-09-30)**.
- **Ollama Cloud** (metered, `$0.20-0.60/1M` bracket): deepseek-v4-flash, deepseek-v4-pro, glm-5.2, kimi-k2.7-code. Existing deployments.

Model overlap per alias: DeepSeek V4 Flash (Zen free + Ollama metered), GLM-5.2 (Synthetic + Ollama), GLM-5.3-Flash (Synthetic + Ollama). Overlaps are partial — balancing is per-alias, not one global pool.

## Layer 1 — Alias topology

Aliases stay; deployments multiply behind them. The ladder per alias is free → subscription → metered:

| alias | tier 1 (free) | tier 2 (subscription) | tier 3 (metered) |
|---|---|---|---|
| `deepseek-v4-flash` | zen-free (DeepSeek V4 Flash free) | — | ollama-cloud |
| `glm-5.3-flash` | — | synthetic (Always-On) | ollama-cloud |
| `glm-5.2` | — | synthetic (Always-On) | ollama-cloud |
| `kimi-k2.7-code` / `kimi-k3` | — | synthetic (`syn:large:vision` → Kimi-K3) | ollama-cloud |

Config shape: same `model_name` listed multiple times with distinct `litellm_params` — that is LiteLLM's load-balancing group. Order in `model_list` does not set priority; strategy does (Layer 2).

## Layer 2 — Deployment balancing

Two candidate strategies, one decision:

- **`simple-shuffle` with weights** — static, predictable, quota-shaped if weights mirror quota: e.g. Synthetic weight 9, Ollama weight 1. Simple, but doesn't react to actual 429s faster than cooldowns do.
- **`usage-based-routing` with RPM/TPM caps on the subscription deployment** — LiteLLM respects per-deployment limits; when the cap is hit it routes elsewhere. Closer to "burn the subscription, then spill."

Either way, three settings carry the failover semantics:
- `cooldown_time` + `allowed_fails` on subscription deployments: quota exhaustion (429/401) cools the deployment, traffic shifts to the next tier automatically, returns when the cooldown expires.
- Keep `num_retries: 0` (already set) so failures fail over rather than retry into a dead upstream.
- Verify on the wire what Zen and Synthetic actually return on quota exhaustion (429 vs 401 vs silent) — one curl each in the spike; the cooldown config depends on it.

Current `routing_strategy: "latency-based-routing"` is wrong for this goal and should change: latency routing drifts to the *faster* provider, not the cheaper one.

## Layer 3 — ZDR constraint

LiteLLM has no ZDR routing input. "Awareness" is therefore:

1. **Config metadata**: per-deployment `zdr` status in the alias topology (in-repo config comment or a structured key), with agreement expiry dates. Initial ledger: zen-go DeepSeek (monthly renewal, expires 2026-09-30), synthetic (EULA/privacy page — no prompt retention, per their docs), ollama-cloud (standard metered retention — treat as non-ZDR for anything sensitive).
2. **Routing enforcement**: ZDR-required workloads resolve to aliases whose *eligible* deployments all carry current ZDR. In practice: a parallel alias namespace (e.g. `zdr/deepseek-v4-flash`) that only maps to ZDR-current deployments, so the constraint is a property of which alias you call, not a per-request flag.
3. **Expiry tracking**: a `cove` CLI status surface (or a scheduled check) that lists agreements and expiry dates, and warns N days before one lapses. Manual list in config; no vendor API to query. When an agreement lapses, the deployment is commented out of ZDR-aliases until renewed.

Honest limitation: expiry dates are operator-maintained. The router trusts the config; nothing verifies the agreement is still live except the operator checking the Go docs page.

## Credential plumbing

`SYNTHETIC_API_KEY`, `OPENCODE_ZEN_API_KEY` join `OLLAMA_API_KEY` in the shared 1Password item pattern → `cove creds` → compose `.env` → `os.environ/` references in `config.yaml.j2`. Same flow as existing keys; new items keyed per provider.

## Verification plan (replay harness)

The existing harness measures balancing directly: fire the same windows repeatedly and count upstream distribution (usage accounting comes from each provider's response). Expected assertions:
- Subscription deployment served until cooldown, then failover to metered
- Recovery after cooldown window
- ZDR alias never resolves to a non-ZDR deployment
- Latency/cost per tier logged from response headers

## Explicitly out of scope (own jam)

Quality-cost routing (pick a cheaper model when the task allows) — custom pre_call hook, unresolved design questions (signals, rewrite rules, eval methodology). See the companion jam session.

**Certified:** config-scale change to `config.yaml.j2` + creds + a small status surface for ZDR expiry; confidence medium — cooldown semantics need the wire-shape check per provider, and the ZDR ledger is operator-maintained trust, not verified guarantees.