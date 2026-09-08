---
title: "Bifrost Gateway Evaluation (Triple-Depth) as LiteLLM Contingency"
created: 2026-09-08
status: Draft
---

# Bifrost Gateway Evaluation (Triple-Depth) as LiteLLM Contingency

Follow-up to [K3's certified musing](./2026-09-08-headroom-k3-recommendation.md), which named Bifrost as the contingency if LiteLLM's CVE drumbeat becomes unacceptable. Protocol: three progressively deeper evaluation frames — repo/deployment shape, security posture, live evidence.

## Depth 1 — Repo & Deployment Shape

`maximhq/bifrost`: Apache-2.0, Go, 7.9k stars, active (last push 2026-09-08, created 2025-03). Versioned monorepo releases (`transports/v2.1.0`, per-plugin tags). OpenAI-compatible `/v1` plus native Anthropic/GenAI endpoint translation; `provider/model-name` aliasing (`openai/gpt-5`, `anthropic/claude-...`) matches Cove's alias need. Official docs cover OpenCode integration (`docs.getbifrost.ai/cli-agents/opencode`) with a generated `opencode.json` provider block. Claimed overhead: 11 µs at 5k RPS.

**IaC fit is genuinely good.** Two configuration modes: file-only `config.json` (declarative, GitOps-oriented, restart-based, UI disabled) or DB-backed with the file as seed/reconciliation source. `source_of_truth: "config.json"` makes the file authoritative. Credentials via `env.VAR_NAME` references — never in the file. This is compatible with Cove's compose + `cove creds` injection pattern. Contrast 9Router, whose dashboard/SQLite config model was the primary disqualifier.

Caveats: the default mode is DB-backed with auth **disabled** (`governance.auth_config.is_enabled=false` default — this matters in Depth 2); `config_store.enabled: false` + present config.json gives strict file-only mode. Zero-config defaults (no auth, dashboard UI) are online-service ergonomics, not hardening — but all closable via config.

## Depth 2 — Security Posture

Two advisories on the ledger (both 2026):

1. **CVE-2026-86242 / GHSA-2qp8-4xgm-fw6g (critical, fixed in transports/v2.0.0):** unauthenticated RCE via custom-plugin HTTP path. Default config (dashboard auth disabled) let anyone POST an `http://` plugin path; the loader downloads and `dlopen()`s it. Mitigations per JFrog: run the statically linked official Docker image (plugin.Open fails), enable management auth, keep the listener off untrusted networks. Cove would satisfy all three passively: digest-pinned official image, localhost binding behind nginx, and the config is operator-controlled anyway.
2. **CVE-2026-55245 / GHSA-w98g-5w9p-p3rc (high):** SSRF deny-list gaps in `isPublicIP` — CGNAT (100.64/10), IPv6 6to4, NAT64, and site-local ranges classify as public, enabling metadata-endpoint (IMDS) probes on dual-stack hosts. Irrelevant for Cove's single-host Docker deployment (no cloud IMDS, no NAT64), but it shows the SSRF surface needs watching.

Pattern comparison: Bifrost has **2 advisories, both fixed, fast patch cadence** (v2.0.0 released with the fix, PR #5763). LiteLLM has 16+ CVEs, a March 2026 supply chain compromise (TeamPCP), and advisories landing ~monthly (latest 2026-08-26, SSRF + credential exfil). The velocity delta is the point: LiteLLM's problem is the drumbeat, not any single bug. Bifrost is not clean — no project in this class is — but its ledger is thin and the fixes are prompt.

## Depth 3 — Live Evidence

- **Sentiment:** Reddit/HN positioning is "LiteLLM alternative for teams that don't want to babysit infra"; the marketing claim "50x faster than LiteLLM" is vendor-authored (their own benchmark post), unverified independently. No independent head-to-head exists.
- **Failure reports:** one notable DEV Community post ("Why I'm Cautious About AI Gateways After My Bifrost Collaboration") — a governance/trust complaint about the *collaboration process*, not a technical defect; the author explicitly says "I am not saying Bifrost steals keys." Treated as noise for a single-operator deployment, but noted.
- **Open issues sampled:** Ollama cloud-key hotfix (#1452, open), Ollama native API request (#1011, open) — the Ollama integration path is provider-grade but not first-class; expect friction routing to `ollama.com/v1` that LiteLLM's `openai/<model>` custom-LLM pattern handles natively. Also #5768 ("require auth for provider endpoint changes") remains open — hardening in progress, not done.
- **Ecosystem drift risk:** vendor is VC-backed (Maxim AI) with an enterprise tier gating clustering/adaptive load balancing; OSS core is real but the roadmap tilt is visible.

## Verdict

**Contingency status: confirmed, upgraded.** Bifrost is the strongest LiteLLM replacement candidate in the 2026 field — the only one with a genuinely IaC-native config model, per-model aliasing, documented OpenCode integration, and a thin (if non-zero) CVE ledger. For Cove it would deploy as a `bifrost` compose profile: file-only `config.json` (aliases for the four Ollama-Cloud models, `env.OLLOMA_CLOUD_KEY`), digest-pinned image, localhost bind, nginx block following the variable-upstream pattern. Known friction: Ollama-Cloud routing is issue-ticket territory (#1452/#1011), not docs territory — prototype that path first.

**Recommendation stands:** keep K3's Option B migration (standalone Headroom, LiteLLM retained as router). Bifrost stays the named contingency if LiteLLM supply chain degrades further — its activation trigger is a LiteLLM event (new critical CVE or compromise), not a Bifrost event.

## Certified

**Option:** Bifrost as named LiteLLM contingency (not now)
**Confidence:** medium-high on capability fit; medium on supply-chain longevity (18-month-old project, VC-backed, enterprise tilt)
**Key evidence:** repo metadata (Apache-2.0, Go, active); CVE-2026-86242 + CVE-2026-55245 with fast fixes (JFrog, GHSA); file-only config.json mode (docs.getbifrost.ai/deployment-guides/config-json); OpenCode doc page (docs.getbifrost.ai/cli-agents/opencode); Ollama friction #1452/#1011.
**Reversibility:** compose profile is additive; removing it restores prior state trivially.
**Dissent recorded:** 18-month track record vs LiteLLM's maturity; enterprise-feature gating may split the OSS core; the critical RCE shows default-config hygiene is user-borne; "50x faster" is unaudited vendor benchmark.