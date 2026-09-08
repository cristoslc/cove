---
title: "Custom Compressor Decision Under Metered Pricing"
created: 2026-09-08
status: Draft
---

# Custom Compressor Under Metered Pricing (Decision Note)

Supersedes the "don't build" verdict in the replay thread. New constraints from the operator:

1. **Subscription model is eroding; assume per-token metering.** Priced with Ollama Cloud GLM-5.3-flash-class rates for all tokens.
2. **Harness portability required.** DCP (opencode plugin) is not a valid answer.

## Measured baseline (from the local opencode store)

Last 30 days across all sessions: **3,063M input tokens, 9.3M output tokens** (22,513 assistant messages). This is the metered bill. Note: `cache.read` is 0 in the store — the earlier "input mostly cache-read" framing came from the `opencode stats` display which double-counts differently; the raw store shows fresh input is the whole bill.

## Metered economics (GLM-5.3-flash pricing applied)

Baseline at $0.20/1M input: **$612/30 days, ~$7,350/year**. At $0.30-0.60/1M: $930-1,858/30d ($11k-22k/yr). Subscription-era "$0.03/day" is dead; metered reality is **$20-62/day**.

Compression value at metered pricing (net of the DCP-class compress-pass overhead, ~15% re-read):

| option | net reduction | $/yr saved @ $0.20/1M | @ 2× | @ 4× |
|---|---|---|---|---|
| Headroom guardrail | 6.3% | $463 | $926 | $1,853 |
| DCP-class, conservative | 40% | $2,499 | $4,999 | $9,998 |
| DCP-class, aggressive | 70% | $4,374 | $8,748 | $17,496 |

Context pressure compounds this: 3.7M avg tokens/session means several sessions already push real model context windows; compression is also a capability unlock (longer working sessions), not just cost.

## Options re-scored under (metered + portable)

| option | portable | reduction | license/audit | build cost | payback |
|---|---|---|---|---|---|
| DCP plugin | ✗ opencode-only | 92-98% structural | open | $0 | n/a — disqualified by portability |
| **Sleev** | ✓ any harness | DCP-class (DCP's successor, same team) | **proprietary, EULA** (Sleev Labs Inc) | ~0.5 wk | days |
| Headroom standalone/tuned | ✓ | 6.3% measured; lossless-reads path could raise it | Apache-2.0 | 0.5-1 wk | 0.2-1.2 yr |
| Custom compressor from scratch | ✓ | whatever we build | ours | 2-4 wk | 1.4-9.6 yr |

**The portability constraint flips the July musing's rejection of Sleev.** It is the only tool that is simultaneously portable-any-harness, DCP-class in reduction, and maintained by the DCP team. Its cost is governance, not engineering: closed source, EULA-governed, local-first but unauditable. Headroom is the open-source portable option but measured 6.3% on tool traffic.

## Verdict

**Do not build from scratch.** Even at 4× current usage, a from-scratch compressor pays back in 1.4-2.4 years — the build cost ($15-24k) swamps the metered savings at realistic adoption. The compressed-context quality question (summary fidelity gating everything downstream) is also solved by DCP's prompt corpus, not by writing new ones.

**Recommended sequence:**

1. **Pilot Sleev** (days of effort): point opencode + one non-opencode harness through it on the same real-session replay harness we built. Validate (a) DCP-class reduction holds at proxy layer, (b) it works with Ollama Cloud upstream, (c) the EULA/telemetry posture is tolerable for a single-operator local deployment.
2. **In parallel, keep Headroom as the open-source hedge**: file/sponsor the lossless-reads feature (the 66%-of-bytes lever we measured). If Sleev's proprietary posture proves unacceptable, an upstream PR to Headroom is the fallback at 0.6-1.4 yr payback.
3. **Custom build only if both fail** — Sleev unacceptable *and* upstream won't take the lossless-reads patch. That is the only world where building is rational, and it starts as a port of DCP's core (deterministic dedup + range summarize), not a novel design.

**Certified:** custom compressor — no. Pilot Sleev — yes, immediately; confidence medium (proprietary risk vs DCP-class savings). Revisit if Sleev telemetry/EULA fails review.

Artifacts: metered-economics math inline above; inputs from the opencode store (30-day token aggregates) and this session's replay measurements.