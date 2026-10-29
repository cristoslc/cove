---
title: "Can Bifrost carry Headroom compression, should it, or should we drop it?"
created: 2026-10-28
status: Ruled
ruled: 2026-10-29
authored-by: standard:cove
---

# Can Bifrost carry Headroom compression, should it, or should we drop it?

This is a decision brief, not an implementation. It answers three questions the operator asked after the dead LiteLLM compression claim was removed and the exit to Bifrost was approved. It grounds every claim in this repository first, then in the upstream projects. It notes the earlier K3 question (standalone Headroom versus LiteLLM) so it is not answered twice.

Related: [the LiteLLM exit musing](litellm-exit.md), [the removed-claim and request-size note](../tech-debt/litellm-headroom-and-request-size.md) (merged in PR #117), [the Bifrost service doc](../services/bifrost.md), and the 2026-09-08 jam sessions on [metered economics](jam-sessions/2026-09-08-custom-compressor-metered-economics.md) and the [real-session replay](jam-sessions/2026-09-08-spike-real-session-replay.md).

## Short answers

- **Can Bifrost use Headroom?** Yes, in principle, but only by chaining Headroom as an OpenAI-compatible hop (keep it in front of Bifrost so the ladder stays intact). The in-process hook path is blocked by the official Bifrost image, which is statically linked and cannot load a Go plugin. Client-side `headroom wrap` works but is per-client and bypasses the neutral `llmproxy.cove` edge.
- **Should it?** No, not now. The only measured value is about 6.3% on real tool-heavy traffic and possibly near zero on tool-role payloads, while the two real gaps (no declared input limit, and a `400` that never cascades) remain the incident's cause and are not answered by compression or by Bifrost.
- **Or drop it?** Yes, and the operator ruled it on 2026-10-29: stay dropped. Revisit only if a measured A/B on the existing replay harness shows a material reduction after the file-read protection gap is addressed, and after the two gaps have a decided policy.

The honest split is: **"can" is yes, "should" is no.**

## Ruling (2026-10-29)

The operator accepted the drop recommendation on 2026-10-29. Compression stays dropped behind Bifrost: no reinstate, no probe, no code. The reopen condition is unchanged: a post-fix replay A/B on the existing harness must show a material reduction after the file-read protection gap is addressed, and the two request-size gaps must have a decided policy. Until both hold, this document is the record and there is nothing to build.

## What was removed, and why that matters here

The removed sidecar was `ghcr.io/chopratejas/headroom`, digest-pinned, published on `127.0.0.1:4001`, with a `headroom_settings:` block in the LiteLLM template. It was removed in PR #117 because the pinned LiteLLM 1.84.0 has no Headroom integration at all: the block was silently ignored, and Headroom's own counters showed one request in its lifetime and zero compression jobs. The full evidence is in the [tech-debt note](../tech-debt/litellm-headroom-and-request-size.md). The important consequence for this brief is that **compression was never running**, so "reinstate it behind Bifrost" is really "build it for the first time", not "move it".

## Mechanism 1: chain it (Headroom as an OpenAI-compatible hop)

**Exists.** Headroom's proxy is a drop-in OpenAI-compatible passthrough: the README says "Proxy: `headroom proxy --port 8787`, zero code changes, any language" and "Any OpenAI-compatible client works through `headroom proxy`". It serves OpenAI `/v1/chat/completions`, OpenAI `/v1/responses`, and Anthropic `/v1/messages`, and its upstream is configurable with `--openai-api-url` or `OPENAI_TARGET_API_URL`. Bifrost supports custom OpenAI-compatible provider instances (`custom_provider_config.base_provider_type: "openai"` plus `network_config.base_url`), and Cove's Bifrost config already uses that pattern for the Synthetic instances.

**The workable order is Headroom in front of Bifrost, not behind it.** The brief's phrasing (Bifrost sends upstream to Headroom) puts Headroom closest to the provider. That collapses the ladder: Headroom has one configured upstream and its model router is limited, so it cannot reproduce the nine-tier, three-provider fallback chain. Putting Headroom in front (`client -> Headroom -> Bifrost -> providers`) compresses once and leaves routing, failover, and the ladder to Bifrost. Headroom forwards to Bifrost with `OPENAI_TARGET_API_URL=http://bifrost:8080/v1`.

**Cost.** A second proxy hop. Headroom claims compression at "well under a millisecond", and a vendor-cited production figure of about 52 ms median proxy overhead; the July musing estimated 100 to 200 ms, so treat the overhead as single-digit-to-low-hundreds of milliseconds and measure it. Plus a resident model (Kompress-v2-base) and its memory, plus Bifrost's own sub-millisecond overhead.

**Streaming and tool calls are the risk to verify, not to assume.** Headroom is designed for transparent passthrough and handles both OpenAI and Anthropic message shapes, so the intent is preservation. The passthrough path is where its bugs land: issue #1112 was a 502 on an incomplete chunked read against an OpenAI-compatible upstream (closed in PR #1513, July 2026). A live streaming and tool-call A/B is required before trusting it.

## Mechanism 2: in-process hook (a Bifrost plugin that calls Headroom)

**The hook surface exists, but it is not usable with Cove's deployed image.** Bifrost documents native Go plugins with `PreRequestHook` (routing), `PreLLMHook` (per-attempt request transform, and it can short-circuit), and `HTTPTransportPreHook` (modify `req.Headers`, `req.Body`, `req.Query`). So a plugin could, in principle, call Headroom out of process and rewrite the request body.

Two blockers:

- The official `maximhq/bifrost` image is statically linked, so Go shared-object plugins cannot be loaded: `plugin.Open` fails with "Dynamic loading not supported". This is stated in a third-party Bifrost guardrail-plugin project README and is consistent with the Go plugin docs, which require `go build -buildmode=plugin` with the exact Bifrost core version. Using this path means building and maintaining a custom Bifrost image from source, which breaks the digest-pin and IaC anchors that are the whole point of the Bifrost deployment.
- A plugin is code Cove would own forever, tied to Bifrost's internal core version, on a gateway chosen partly because it was statically linked and simple to verify.

**Possible escape hatch, unverified:** the docs say `HTTPTransportPreHook` "works with both native `.so` and WASM plugins". If the official image includes a WASM loader and the WASM host exposes an HTTP client, a WASM plugin could call Headroom without a custom image. I could not verify either condition, and a WASM plugin adds its own build and trust surface, so this is a maybe, not a plan.

## Mechanism 3: client-side wrap

**Exists.** `headroom wrap opencode` starts the proxy, injects an OpenCode config with a `headroom` provider, registers Headroom MCP tools, and launches the agent. The README marks OpenCode as supported, as it does `omp` and several others, and `headroom unwrap` reverses it. The wrap's upstream is pointed at a third-party gateway with `--openai-api-url` or `OPENAI_TARGET_API_URL`.

**Implications for `llmproxy.cove` and the clients.** The wrap is per-client and lives on each client machine. It bypasses the product-neutral edge, so the one-token, one-endpoint model is replaced by per-client Headroom config plus a Headroom proxy that must reach Bifrost. Any client not wrapped gets no compression. For Cove's four clients this is four install-and-configure surfaces, and it reintroduces exactly the per-client credential spreading the exit design worked to remove. It is a pilot tool, not a product-neutral deployment.

## Evidence table

| Claim | Source |
| --- | --- |
| Headroom proxy is an OpenAI-compatible drop-in; any OpenAI-compatible client works through it | [headroomlabs-ai/headroom README](https://github.com/headroomlabs-ai/headroom) |
| Headroom serves `/v1/chat/completions`, `/v1/responses`, and `/v1/messages` | same README, "Output token reduction" |
| Headroom upstream is configurable (`--openai-api-url` / `OPENAI_TARGET_API_URL`) | same README, footnote 1 |
| `headroom wrap opencode` exists; OpenCode is supported | same README, "Agent compatibility"; [docs.headroomlabs.ai/docs/opencode](https://docs.headroomlabs.ai/docs/opencode) |
| Telemetry beacon is on by default; `HEADROOM_BEACON=off`, `DO_NOT_TRACK=1`, `HEADROOM_OFFLINE=1`; parsing is fail-open | same README, "Telemetry"; [docs.headroomlabs.ai/docs/limitations](https://docs.headroomlabs.ai/docs/limitations) |
| Offline needs `cdn.pyke.io` (ONNX Runtime) and `huggingface.co` (Kompress-v2-base), or pre-seeding | docs limitations, "Corporate networks" |
| Passthrough 502 on incomplete chunked read, closed July 2026 | [issue #1112](https://github.com/headroomlabs-ai/headroom/issues/1112) and PR #1513 |
| LiteLLM's Headroom path needs 1.92+ and is a `guardrails:` entry; LiteLLM also has a `HeadroomCallback` SDK hook | LiteLLM headroom docs; headroom `litellm.mdx`; [tech-debt note](../tech-debt/litellm-headroom-and-request-size.md) |
| Bifrost supports custom OpenAI-compatible provider instances | [docs.getbifrost.ai/providers/custom-providers](https://docs.getbifrost.ai/providers/custom-providers); Cove's own [Bifrost config](../services/bifrost.md) |
| Bifrost Go plugin hooks can modify the request body (`HTTPTransportPreHook`, `PreLLMHook`) | [docs.getbifrost.ai/plugins/writing-go-plugin](https://docs.getbifrost.ai/plugins/writing-go-plugin) |
| Official Bifrost image is statically linked; Go plugins cannot load | [go-routine-id/bifrost-guardrail-plugin README](https://github.com/go-routine-id/bifrost-guardrail-plugin); Go plugin docs |
| WASM plugin path exists, HTTP capability unverified | writing-go-plugin ("Works with both native `.so` and WASM plugins") |
| Bifrost `400 (caller_fault)` does not cascade a rule-provided fallback chain | [litellm-exit musing](litellm-exit.md), "Ladder fit" |
| Measured Headroom reduction on Cove tool traffic was 6.3%; file reads are tag-protected (no-op) | [real-session replay](jam-sessions/2026-09-08-spike-real-session-replay.md) |
| Metered baseline: 3,063M input tokens/30 days, about $7.35k/yr at $0.20/1M | [metered economics](jam-sessions/2026-09-08-custom-compressor-metered-economics.md) |
| The dead session was 415,724 tokens; no declared input limit; a `400` does not cascade | [tech-debt note](../tech-debt/litellm-headroom-and-request-size.md) |

## Should it: value must be measured, and the two gaps come first

**Value.** The only Cove-specific measurement is 6.3% on tool-heavy traffic, and the dominant payload (OpenCode file reads, about two thirds of tool bytes) is protected by Headroom's tag protector, so it comes back byte-identical. Headroom's own README agrees that savings "scale with how repetitive the payload is" and that prose "compress very little". What would show compression earning its place is a replay A/B on the existing harness measuring input tokens, cost, latency, and answer quality, with the file-read protection relaxed to a lossless fold. That A/B is runnable today; the earlier run predates any such fix, so 6.3% is a floor, not the ceiling, and a fresh number is the gate.

**What the A/B cannot fix.** The incident was a provider refusing a request that fit its advertised window, and the `400` never tried the group's other deployments. What the record supports about the size is narrower than it looks:

- The session had used 415,724 input tokens, and that measurement was taken before the turn's own content was added. The true sent size is therefore unknown, and the client's figure may understate it.
- Adding the requested 32,768 return gives 448,492; reserving the provider's full 65,536 output allowance gives 481,260. Both fit the advertised 524,288.
- The refusal therefore only bounds the real ceiling from above. The true ceiling sits at or below roughly 448,000, and nothing recorded places it lower.

A 6.3% reduction of the recorded input lands near 389,000, which fits under any ceiling at or above that. So the refusal does not show that a single-digit reduction could not have saved the session, and it does not fix the reduction that would have been required: that is the difference between the true sent size and a ceiling nobody has measured. What the refusal does show is that the two gaps remain the incident's cause regardless, because a request refused below its own group's other deployments never reaches them, and that is independent of the gateway and of compression.

**Do Bifrost or Headroom answer either gap?** Not today.

- Gap 1 (no declared input limit): Bifrost exposes model metadata (`ContextLength`, `MaxInputTokens`, `MaxOutputTokens`) to plugins through `ctx.GetModelInfo`, and keeps a model catalog. But using it for pre-dispatch size validation needs a plugin, which the static official image cannot load, and I could not verify a built-in pre-dispatch rejection. The declared metadata is also the very advertisement that is unverified here. Bifrost does not close gap 1 as deployed.
- Gap 2 (`400` does not cascade): Bifrost's documented behavior is that a `400 (caller_fault)` does not cascade a rule-provided fallback chain. Bifrost reproduces the gap, it does not close it.

So compression is a distraction from the two gaps, and the two gaps are more valuable to close first.

**Cost and risk, weighed.** A second proxy hop and its latency; a resident model and RAM; a model/runtime download from `huggingface.co` and `cdn.pyke.io` that fights Cove's offline-first posture and would widen Bifrost's fail-closed DNS allowlist (currently exactly `api.synthetic.new`, `ollama.com`, and `getbifrost.ai`); telemetry on by default with a fail-open parser; Headroom's own CVE-2026-32920 and the CompressionAttack class; and a new SBOM and update-hold surface. Apache-2.0 licensing is fine and the project is very active. None of this is disqualifying on its own, but it is a lot of surface for a capability that never ran.

## Recommendation (accepted 2026-10-29)

**Drop it, and stay dropped.** The operator accepted this recommendation on 2026-10-29. Do not reinstate Headroom behind Bifrost. Point the next effort at the two gaps, not at compression. Reopen the question only when a replay A/B, run after a lossless-read fix, shows a material reduction, and when the two gaps have a decided policy.

**Strongest counter-argument.** The metered economics are real and compounding: 3,063M input tokens per 30 days is about $7.35k/yr at $0.20/1M, so even 6.3% is roughly $460/yr, and a lossless-read fix plausibly lifts the reduction into the 25% band, which is $1.8k/yr at four times current usage. Compression is also a capability unlock for the long sessions this platform runs, not only a cost saving. Headroom is maintained, Apache-2.0, and already integrated with the OpenAI and Anthropic paths, so the cost is bounded and reversible. If the operator weights the metered bill and long-session capability above the added surface, reinstating is defensible, but it should follow a measurement, not precede one.

## Smallest change set

**For "reinstate"** (to be done only after the gating measurement):

1. Add a `headroom` compose service, digest-pinned to `ghcr.io/headroomlabs-ai/headroom`, loopback-bound, with `HEADROOM_BEACON=off`, a memory limit, and an offline model/ONNX pre-seed step.
2. Set its upstream to Bifrost (`OPENAI_TARGET_API_URL=http://bifrost:8080/v1`).
3. Put Headroom in the client path: flip the `llmproxy.cove` upstream (or add one nginx hop) so clients hit Headroom first, then Bifrost.
4. Extend the egress allowlist or the pre-seed so the model/runtime download never needs the open internet.
5. Add a live streaming and tool-call smoke plus a replay A/B gate, and a test that fails if compression does not actually run.

**For "drop":** nothing to change. PR #117 already removed the service and the claim, and the [tech-debt note](../tech-debt/litellm-headroom-and-request-size.md) records it. Record this decision against that note and move the next effort to the two gaps.

## What is unknown or unverified

- Whether Headroom preserves streaming, tool calls, and provider prompt-cache behavior when chained in front of Bifrost. The passthrough path is where its bugs land; a live A/B is required.
- Whether the official Bifrost image supports WASM plugins, and whether a WASM plugin can open an HTTP connection to Headroom.
- Whether Bifrost has any built-in pre-dispatch input-limit validation, versus only plugin-visible model metadata.
- The real provider input ceiling (gap 1) and the true size of the refused request: the 415,724 figure predates the turn's own content, so neither is measured, and the ceiling probe last hit `429`.
- Whether a `400` can be made to cascade at all (gap 2). This is a policy question, not a measurement.
- Headroom's behavior in a Cove-shaped offline deployment at the current version, including the beacon's fail-open parsing and the exact pre-seed surface.
- The achievable reduction on Cove's own traffic after the file-read protection gap is addressed. The 6.3% figure predates any fix and should not be treated as the ceiling.

## Fold-in: the earlier K3 question

The unreleased K3 prompt asked whether standalone Headroom should be used *in addition to* LiteLLM (Option A) or *instead of* it (Option B), and named Bifrost as the LiteLLM contingency. That was answered in [the K3 musing](jam-sessions/2026-09-08-headroom-k3-recommendation.md) and, in practice, by events: Option B cannot express the ordered ladder, and the LiteLLM exit chose Bifrost, which preserves it. This brief supersedes the K3 framing: the live question is no longer "standalone versus sidecar" but "should any headroom-style compression sit in front of Bifrost at all", and the answer is the same for the same reason, the ladder and the two gaps matter more than a single-digit reduction.

## Certified

**Ruling:** Drop accepted by the operator on 2026-10-29; compression stays dropped and the reopen condition is unchanged.
**Confidence:** medium-high on capability (the chain works), high on the "should not, yet" call given the two unaddressed gaps.
**Key evidence:** measured 6.3% reduction with file-read tags protected ([replay](jam-sessions/2026-09-08-spike-real-session-replay.md)); the two gaps are the incident's cause ([tech-debt note](../tech-debt/litellm-headroom-and-request-size.md)); Bifrost's official image cannot load Go plugins ([guardrail-plugin README](https://github.com/go-routine-id/bifrost-guardrail-plugin)); a `400` does not cascade in Bifrost ([exit musing](litellm-exit.md)); telemetry and offline downloads are opt-out and pre-seed concerns ([README](https://github.com/headroomlabs-ai/headroom), [limitations](https://docs.headroomlabs.ai/docs/limitations)).
**Reversibility:** high. Reinstating is one compose service plus a client-path flip; dropping needs no change.
**Dissent recorded:** the metered bill and the long-session capability case are real, and a post-fix A/B could justify reinstating; the 6.3% figure is stale and should not be read as final.
