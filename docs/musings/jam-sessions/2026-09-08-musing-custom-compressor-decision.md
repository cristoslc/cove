---
title: "Musing: Custom Compressor for Cove — Wire Format, Ownership, and What We Learned"
created: 2026-09-08
status: Draft
---

# Custom Compressor for Cove — Wire Format, We Learned, and Where This Ends

Decision note consolidating today's chain. Reads in order after the six musings/spikes below.

## The chain so far

1. [K3 certified musing](./2026-09-08-headroom-k3-recommendation.md) — Option B (standalone Headroom over LiteLLM), later downgraded
2. [Bifrost evaluation](./2026-09-08-bifrost-triple-depth-evaluation.md) — named LiteLLM contingency, not adopted
3. [Guardrail spike](./2026-09-08-spike-litellm-native-headroom-guardrail.md) — LiteLLM ≥1.92 native Headroom guardrail verified end-to-end
4. [Replay spike](./2026-09-08-spike-real-session-replay.md) — 6.3% real-session reduction, +4 addenda to root cause
5. [Metered economics](./2026-09-08-custom-compressor-metered-economics.md) — subscription model eroding, harness portability required
6. [Sleev account-free spike](./2026-09-08-spike-sleev-account-free.md) — local-yes, self-hostable-no, custom providers passthrough-only

## Constraints settled today

- **Metered pricing is coming.** Measured from the opencode store: 3,063M input tokens / 30 days. At GLM-5.3-flash-class metering ($0.20/1M): $612/mo, ~$7.4k/yr. Subscription-era economics ("$0.03/day") are gone; compression carries real dollar weight.
- **Harness portability required.** No opencode-only plugins. Whatever we adopt must sit behind Claude Code, OpenCode, Codex, OpenRouter-shaped clients — any provider, transparently.
- **Cove is not a SaaS.** Build costs are operator+agent sessions and cove-profile surface, not consultancy invoices. The $15-24k "build cost" from the earlier decision note is discarded — the real cost is days of agent time and one compose profile's footprint.
- **No accounts for spikes.** Sleev guest mode proved local-only-yes, self-hostable-no: closed binary, license-server gate, telemetry opt-out enterprise-only, and — decisive — **custom providers are opaque passthrough by design**, so Ollama Cloud traffic is never optimized. Not viable as a Cove service.
- **Sleev pilot result:** account-free works (guest mode, no sign-in), requests route correctly, but 0.0% reduction on our replay traffic — passthrough-only for custom providers. The 65% claim is scoped to live named-provider sessions. Can't be measured without an account we won't create.

## What the replay harness taught us about Headroom

The 6.3% headline measurement decomposed into three layers, in discovery order:

1. **XML tag protection** (the big one): opencode's file-read format is `<path>…</path> <type>file</type> <content>55K</content>`. Headroom's tag protector treats the whole payload as byte-exact blocks: 55,129 chars → 56 chars of placeholders → nothing to compress → `router:noop`. Proof: identical content with tags rewritten away compresses **25%**.
2. **Missing dependency**: with `trafilatura` absent, the html strategy silently passes through (ratio 1.000). Installed: `strategy=html, ratio=0.883` — a real 11.7% cut on the XML envelope.
3. **Config flag, not env**: `ContentRouterConfig.compress_tagged_content` (default `False`) — `True` exposes tag-wrapped content to the compressors. No env hook; travels via `ProxyConfig`.

Remaining open item: the *running gateway's* `/v1/compress` pipeline still noops where the library-level `apply()` compresses (its cache-mode posture diverges; not root-caused within the timebox). The library-level truth stands and is what the build decision needs.

## Decision

**Do not build a custom compressor. Do fork nothing. Update the Cove Headroom profile.**

The fix is config-or-small-patch scale inside the existing profile:

1. Set `compress_tagged_content=True` in the profile's pipeline config so opencode's wire envelope exposes its body
2. Ship `trafilatura` in the image so the html strategy actually runs (today it silently no-ops)
3. Keep fresh reads byte-exact by gating (1) behind the read-lifecycle state — fresh verbatim, stale/superseded folded
4. Verify in the replay harness: target the 25% band (bare-content rate); 11.7% is the conservative floor
5. If the gateway pipeline divergence (open item) blocks (1), file it upstream with our A/B evidence — the issue text is already written in the replay musing's addenda

Why this beats both alternatives at metered economics:
- **DCP-class build**: 1.5-3.4 yr payback even ignoring build cost; DCP itself is disqualified by the portability constraint (opencode-plugin-only); Sleev by self-hostability. The only portable DCP-class alternative left is the one we'd build — but the measured 25% band from Headroom's *existing* compressor, unlocked by config, captures the majority of the metered savings (25% of $7.4k/yr ≈ $1.8k/yr) for a fraction of the effort.
- **Sleev**: disallowed — not self-hostable in Cove's sense (closed binary, license server, telemetry opt-out enterprise-only).
- **Custom compressor**: still on the shelf. It becomes rational only if the config fix underdelivers AND upstream won't take the read-lifecycle gating patch — the same fork, with better evidence than yesterday's version.

**Certified:** config fix in the Cove Headroom profile; confidence medium-high (config field proven at library level; gateway-pipeline divergence is the open risk). Build-from-scratch reopens only if the profile fix fails in the replay harness or upstream refuses the lifecycle gating patch.

## Open items carried forward

- Gateway `/v1/compress` vs library `apply()` divergence — root cause and fix (upstream issue candidate)
- `compress_tagged_content` needs a read-lifecycle gate for byte-exact fresh reads (upstream patch candidate)
- Replay-vs-live gap: the agent-cooperative optimization path (Sleev-style toolkit injection) is unmeasured by our one-shot replay; a live harness A/B on a Cove session would close it
- Bifrost contingency: unchanged, trigger = LiteLLM supply-chain event