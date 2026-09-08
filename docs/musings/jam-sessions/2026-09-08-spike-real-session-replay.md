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

Replay artifacts: `/var/folders/.../opencode/spike-replay/` (`session-owui-sso.json`, `replay-messages.json`, `replay-windows.json`), spike config in `/var/folders/.../opencode/spike-litellm-headroom/`.