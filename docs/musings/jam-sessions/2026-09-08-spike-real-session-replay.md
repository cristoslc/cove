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

## Addendum 2: why headroom underperforms — and what would fix it

Dug into *why* 6.3%. Not a bug: three deliberate design layers each shave the effective compression on opencode traffic.

**1. opencode's file-read format is structurally protected.** The dominant payload in real sessions — 66% of tool bytes across the five windows — is `<path>…<type>file<content>1: …` structured read output. Headroom's content router recognizes this shape and no-ops it **by design**, regardless of role, tool-name exclusions, or profile (`coding`'s `protect_reads: True`; synthetic tests: same content bare → 10% compressed, XML-wrapped → 0%). Rationale: the agent byte-patches against exact file content; lossy compression of a Read is how you get corrupted edits. `DEFAULT_EXCLUDE_TOOLS` (Read/Glob/Grep/Write/Edit) plus the XML-structure guard enforce it. Our 12.6% best window compressed the 34% "other" bucket (bash output, prose) and nothing else.

**2. Net-cost gate (#856).** Mutating a message deep in a conversation busts the provider prompt-cache prefix for everything after it. The router's break-even gate (`ΔT vs P_alive·(w−r)·S`) skips mutations whose cache-bust cost exceeds the saving — correct for cache-mode economics, and another reason whole-conversation replays see noops mid-window (`router:mixed:0.71` on one deep window: 23 tokens saved of 17,261).

**3. Coding profile posture.** `savings_profile=coding` defaults: `protect_analysis_context=True`, `force_kompress=False`, delta-only cache mode. Each is individually defensible for interactive coding (fidelity + cache stability), and collectively they bound real-world savings far below the README's headline.

**What would make it more efficient (ranked by measured leverage):**

1. **Relax the file-read structure guard** — the single biggest lever (66% of payload bytes). A lossless path for reads (SmartCrusher-style line folding, or CCR-only truncation keeping head/tail) would attack the exact bytes that dominate. Upstream has the mechanism (`read_maturation` for stale/superseded reads) but leaves fresh reads fully protected. A Cove-tuned profile with `HEADROOM_PROTECT_READS=0` + lossless-only on reads is testable without code changes if the env var can be pinned — env-var propagation through the CLI re-exec needs confirming (the `/health` `savings_profile` field did not reflect env overrides in this spike).
2. **Bigger `--target-ratio`** — the `general` profile + `--target-ratio 0.5` path is more aggressive than `coding`'s emergent 0.75-0.94 ratios; untested here because env vars didn't propagate, flagged for re-test.
3. **`--lossless` mode** — no-CCR lossless compaction with marker-free SmartCrusher may find savings in bash output that the strict profile skips; also untested (flag exists, spike scope ended).
4. **Accept the design**: if byte-exact reads matter (they do for coding), 6-13% may simply *be* the honest ceiling for transparent compression on agent traffic, and DCP's model-driven summarization is the only path to 90%+ reductions.

**Spike-environment caveats:** `/health`'s `savings_profile` and `target_ratio` fields did not reflect env overrides in any of 5 launch configurations (CLI flag, `env` prefix, exported env, `create_app()` defaults, direct `ProxyConfig`) — possibly the fields report the *nominal* profile rather than the effective one, but the compression behavior (0% on XML-wrapped reads) was invariant across all launches, so the protection is in the content router, not the profile plumbing.

## Addendum 3: root cause found — XML tag protection, not role protection

Mechanically isolated (A/B on identical bytes, protections toggled):

- **opencode's file-read format is three XML tags** — `<path>…</path>`, `<type>file</type>`, `<content>55K of file</content>`. Headroom's Rust tag protector (`protect_tags`) treats the whole payload as protected blocks: 55,129 chars → 56 chars of placeholders + byte-exact tag blocks restored after compression. The compressor sees a 56-char body, finds nothing worth compressing, and the net-cost gate emits `router:noop`. **The noop is tag-structure-induced, not a role rule** (earlier attribution corrected).
- **Identical content, tags rewritten away** (`FILE: deploy.sh` prefix, no XML): **13,877 → 10,464 tokens, 25% compressed** via `router:code_aware:0.31`. So the code-aware compressor handles this exact content fine — the XML wrapper is what blocks it.
- Also corrected: `HEADROOM_PROTECT_READS` defaults **off** ("0"); read-protection only engages for detected cat/sed/head read commands paired with tool_use history — irrelevant to our synthetic messages. The `HEADROOM_EXPERIMENTAL_READ_KEEP_RATIO=0.5` knob never fired because the exp path also requires read-command detection (`_protect_read_tool_ids`).

**Efficiency answer, updated:** the highest-leverage lever is precisely this tag-protector interaction. For `<content>`-style tag blocks (whole-file payload inside one tag), byte-exact protection is the correct default for fresh reads, but a **lossless fold of the stale/superseded read bodies** (the read-lifecycle machinery already exists) would attack the 66% bucket without byte-risk on fresh ones. Untestable via env in this spike: `HEADROOM_EXPERIMENTAL_READ_KEEP_RATIO` requires read-command detection that replay traffic can't produce. The Cove-relevant ask upstream: extend `read_maturation`/lossless folding to cover opencode's `<path>/<content>` wire shape — that one feature converts Headroom from 6-7% to plausibly 25%+ (the bare-content rate) on this workload, without any custom compressor.

## Addendum 4: wire-format question answered — yes, and the lever is closer than the musing above claimed

"Can we build a custom wire-format extension?" — tested directly at the library API level. Results:

1. **The tag protection is a config field, not code:** `ContentRouterConfig.compress_tagged_content` (default `False`). `True` protects only tag *markers*, exposing the content between them for compression. No env hook exists — it must be set through `ProxyConfig` → pipeline kwargs (which is why every env-var attempt in this spike failed; the knob lives at config-object level).
2. **A second, unrelated gap:** with the library default, the router dispatches our XML read to the **HTML strategy**, but `HTMLExtractor` lazily loads `trafilatura` — absent from the install, so the strategy returned passthrough, ratio 1.000. After `uv pip install trafilatura`: `compress()` returns `strategy=html, ratio=0.883` — a real 11.7% cut on the XML-wrapped read.
3. **At the message-`apply()` level the cut lands:** `router:html:0.88`, 13,893 → 12,274 tokens. The adaptive `min_ratio` bar (relaxed/aggressive, both defaulting 1.0) accepts 0.88. The tool-role lossy-unmarked guard (which would skip an unrecoverable lossy result) does not include the html strategy, so no CCR-marker rejection either.
4. **Remaining discrepancy:** the *running gateway's* `/v1/compress` still noops the same content even with trafilatura installed — the gateway's pipeline (cache-mode posture, its own router instance/caches) diverges from the direct-library call. Not root-caused within the timebox; the library-level truth is what matters for the build decision.

**Answer to the operator's question:** yes, this is a wire-format problem, and yes, a wire-format extension is the fix — but it's a *configuration* extension, not a new protocol. Concretely: (a) set `compress_tagged_content=True` (markers-only protection) in the Cove profile so opencode's `<path>/<type>/<content>` envelope exposes its body to the existing HTML/ML compressors; (b) ship `trafilatura` in the image so the html strategy actually extracts (today it silently passthroughs); (c) for byte-exactness on *fresh* reads, gate (a) behind the read-lifecycle state (fresh → verbatim, stale/superseded → fold) rather than a blanket flag. Each item is config-or-small-patch scale, inside the Cove profile — no fork needed, no custom compressor needed for the first tranche. Expected recovery on this workload: the 25% bare-content rate is the realistic band (the 0.88 html-extractor ratio on the XML envelope is the conservative floor).

Replay artifacts: `/var/folders/.../opencode/spike-replay/` (`session-owui-sso.json`, `replay-messages.json`, `replay-windows.json`), spike config in `/var/folders/.../opencode/spike-litellm-headroom/`.