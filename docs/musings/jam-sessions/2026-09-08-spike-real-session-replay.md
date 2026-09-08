---
title: "Spike: Real-Session Replay Through LiteLLM Native Headroom Guardrail"
created: 2026-09-08
status: Draft
---

# Spike: Real-Session Replay Through LiteLLM Native Headroom Guardrail

Follow-up to the [guardrail spike](./2026-09-08-spike-litellm-native-headroom-guardrail.md), which gated adoption on one question: does the guardrail save tokens on **real OpenCode workloads** (tool-result-dominated traffic), given the content router no-ops `role: "tool"` rows?

## Method

1. Exported the heaviest tool-traffic session from the local opencode store (`opencode export`): "owui SSO login failure for lldap user" — 1,287 bash + 234 read + 60 grep calls, 4.4 MB of tool output. Pure debugging/ops workload, representative of Cove agent sessions.
2. Converted the export to OpenAI chat format (opencode `tool` parts → `role: "tool"`, text parts → `user`/`assistant`): 2,211 messages, ~1.18M tokens.
3. Sliced into 40-message tool-heavy windows (≥10 tool rows each); replayed the 5 densest through the spike stack (litellm 1.100.0 → guardrail → headroom 0.37.0 → mock upstream) twice each: guardrail active vs `x-headroom-bypass: true` control.

## Results

| window | guardrail | tok (guard) | tok (bypass) | saved | latency (guard) |
|---|---|---|---|---|---|
| 0 | on | 53,161 | 60,822 | 7,661 | 10.5s |
| 1 | on | 21,854 | 22,394 | 540 | 2.3s |
| 2 | on | 37,253 | 38,137 | 884 | 3.2s |
| 3 | on | 26,443 | 27,026 | 583 | 1.5s |
| 4 | on | 16,180 | 16,986 | 806 | 3.5s |
| **total** | | **154,891** | **165,365** | **10,474** | |

**Token reduction on real agent traffic: 6.3%.** Best window 12.6%, typical 2-5%.

Window 0 (the 12.6% case) is 98% tool bytes by volume — so compression *does* touch tool rows sometimes. The variance suggests the router compresses a subset (likely large repetitive JSON/log-shaped tool payloads that look like the prose it was benchmarked on), and no-ops the rest. The earlier spike's flat `router:noop` on synthetic tool rows was partially misleading: real tool output is a mixed bag, and most of it still passes through uncompressed.

Latency: 1.5-10.5s added per request for compression decisions. On the 237 KB window that's 10.5s wall-clock for 7.6K tokens saved. For interactive coding this is perceptible; for background/batch agent runs it is not.

## Verdict

**The 60-95% headline claim does not transfer to real OpenCode tool traffic. Measured: 6.3%.** At Ollama Cloud input pricing the absolute savings on a heavy session (~10K tokens/window × N windows) are real but modest, and the latency cost is non-trivial for interactive use.

**Certified:** native-guardrail A-path is mechanically sound but **not currently worth the pin bump for token savings alone** (6.3% ≪ 60-95% claimed). The decision for Cove should be driven by the other guardrail capabilities (CCR retrieval, spend accounting, guardrail observability in the Logs UI), not compression ROI. Keep LiteLLM at 1.84.0 + sidecar, or retire compression entirely until upstream improves tool-role routing. Re-test on a future Headroom release that routes tool content.

## Addendum same day: head-to-head with DCP (standalone test function)

Ran DCP's algorithm shape as a standalone test function on the **same five windows**: deduplication first (0% — the real session has no exact-duplicate tool calls), then DCP's `compress` path — the window serialized and summarized by a real model (MiniMax M2.7:cloud via Ollama Cloud, $0.20/1M, the cheapest available; the July musing's 50-70% DCP claim context) using DCP's actual `compress-range.ts` system prompt, summary written back in place of the range.

| window | original | DCP prompt cost | DCP summary | DCP net ctx | DCP reduction | headroom replay |
|---|---|---|---|---|---|---|
| 0 | 60,822 | 79,692 | 938 | 1,188 | **98%** | 12.6% |
| 1 | 22,394 | 27,349 | 672 | 922 | **96%** | 2.4% |
| 2 | 38,137 | 48,361 | 1,214 | 1,464 | **96%** | 2.3% |
| 3 | 27,026 | 35,152 | 1,777 | 2,027 | **92%** | 2.2% |
| 4 | 16,986 | 22,360 | 966 | 1,216 | **93%** | 5.0% |
| **avg** | | | | | **95%** | **6.3%** |

This is the honest DCP-vs-Headroom head-to-head the July musing said nobody had published.

**Reading it fairly, three caveats:**

1. **DCP's number is the structural ceiling, not a free win.** 95% is what replacing 40 messages with one summary achieves; DCP's model-driven selection in real sessions triggers later (nudges at 60% context per this repo's `dcp.json`), so realized-session savings are lower. But even discounted 3-5×, DCP compresses an order of magnitude more.
2. **The compress pass itself is not free.** 213K prompt tokens to summarize 5 windows (~$0.049 at MiniMax pricing — cheap, but nonzero, and the summary model's quality gates what survives). Headroom's compression is $0 local compute with no quality-chokepoint model, but it only removes 6.3%.
3. **The mechanisms are complementary, not competing.** DCP's lossy summary dominates context reduction; Headroom's guardrail is transparent, zero-cost, and needs no model awareness. The July musing's "DCP for short sessions, Headroom for long" inverted here: on Cove's actual tool-heavy sessions, the transparent proxy is the weak performer and the model-aware plugin is the strong one.

**Revised certified comparison:** DCP (already installed in this OpenCode via `@tarquinen/opencode-dcp`) delivers ~15× the context reduction of the LiteLLM+Headroom native guardrail on identical traffic. The proxy-compression premise — "transparent beats model-aware" — does not survive contact with measured tool-role data. Headroom standalone (Option B) keeps its CCR/memory/learn differentiators, but its compression layer is the weakest link for this workload.

Replay artifacts: `/var/folders/.../opencode/spike-replay/` (`session-owui-sso.json`, `replay-messages.json`, `replay-windows.json`), spike config in `/var/folders/.../opencode/spike-litellm-headroom/`.