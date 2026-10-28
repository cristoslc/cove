# LiteLLM Headroom and request-size gaps (2026-10-28)

This note records one resolved defect and two independent gaps found while tracing it. The defect is fixed in the same pull request by removing the dead claim. The two gaps are reported, not fixed.

## Summary

- **Headroom compression never ran.** The pinned LiteLLM 1.84.0 has no Headroom integration, so the `headroom_settings:` block was silently ignored. The inert block and the sidecar service are removed.
- **No declared input limit.** The model groups declare no `max_input_tokens`, so nothing validates a request's size before dispatch.
- **A `400` does not cascade.** A provider that refuses an oversized request does not cause the group's other deployments to be tried.

## The compression defect, and why the port was not the cause

The LiteLLM image is pinned to `litellm[proxy]==1.84.0` in `compose/litellm/Dockerfile`. Inside the running `cove-litellm` container, a search of the installed package for `headroom` finds only an unrelated budget-reservation comment and a string in the UI JavaScript bundle. There is no guardrail, no `headroom_settings` parser, and no Headroom code path.

LiteLLM's own documentation confirms the shape: Headroom is a `guardrails:` entry (`guardrail: headroom`, `mode: pre_call`, `api_base: ...`) and requires LiteLLM 1.92 or later. There is no top-level `headroom_settings` key at any version. The old block was therefore inert at the pin, and the wrong endpoint port was a second, independent error on top of it.

The sidecar's own counters confirm it never received compression work. After about 40 hours of live agent traffic through LiteLLM:

- `headroom_requests_total` was 1, and that one request was a probe, not a compression job.
- `headroom_tokens_saved_total` was 0.
- `/stats` reported `requests_compressed: 0`.

The image itself fixes its listen port at 8787: its baked command is `headroom proxy --host 0.0.0.0 --port 8787` and its healthcheck probes `http://127.0.0.1:8787/readyz`. The same image also exposes a stale 4001 and bakes `HEADROOM_PORT=4001` into its environment, but the running command ignores both. Cove published `127.0.0.1:4001:4001`, which mapped a port nothing listened on, and the template pointed at `http://headroom:4001`.

The live LiteLLM config carried `headroom_settings: {enabled: true, endpoint: http://headroom:4001, fallback: direct}` and the proxy started healthy. That is the silent-ignore behaviour: a configuration that names a capability the pin does not implement, accepted without error.

## Decision, and what changed

Operator ruling, 2026-10-28: switch to Bifrost, do not bump LiteLLM. The framing that matters is that compression was never running, so the exit changes nothing about capability. That is stronger and more accurate than saying a working capability is being given up.

The reasons a bump was rejected:

- The LiteLLM exit is already approved, with a freeze on pin bumps and the pin held at 1.84.0.
- A working guardrail needs at least 1.92. The last safe release after the October supply-chain compromise is 1.106.2, which is 22 minor versions of new vendor surface on a pipeline compromised twice in seven months.
- The measured gain was about 6.3% on real tool traffic, and Headroom no-ops tool-role messages, so the realised gain may be near zero.
- The native guardrail is fail-closed: when Headroom is down, requests return 502. On a machine that hosts agents all day, turning a compression outage into an agent outage is the wrong shape.

The changes in this pull request:

- Removed the inert `headroom_settings:` block from `compose/litellm/config.base.yaml`, with a comment recording the version requirement and the evidence.
- Removed the headroom service from `compose/docker-compose.yml` and `compose/litellm/docker-compose.yml`. No port is published and no healthy-looking container remains for a stage that does no work.
- Removed the headroom environment template from `compose/bringup.yml`, the status tuple from `cli/cove/status.py`, and the compression promise from the `cove litellm` help text.
- Replaced the tests that pinned the claim with a negative guard: `headroom_settings` must not return without the supported `guardrails:` form, a pin that implements it, and a test that fails on a pin which ignores it.
- Dropped the unused `sbom/headroom.cdx.json`.

## Gap 1: no declared input limit

The live overlay declares 21 deployments across eight model groups, and none sets `max_input_tokens`. Nothing therefore validates a request's size before dispatch.

The numbers on both sides agree, and the refusal contradicts both:

- The client declares `cove/text:standard` as `limit.context: 524288` and `limit.output: 32768`.
- The provider metadata for `hf:deepseek-ai/DeepSeek-V4.1-Flash` says `context_length = 524288` and `max_output_length = 65536`.
- The session that died had used 415,724 tokens, measured rather than estimated.

Request plus requested return came to 448,492 against 524,288. Even reserving the provider's full output allowance it is 481,260. Both fit. The provider refused with a `400` anyway.

Three explanations remain, and the evidence favours the middle one:

1. The client's figure understates what was actually sent, because the turn's own content was added after the measurement.
2. The provider serves less than it advertises.
3. The provider's tokenizer counts the same text higher than the client's.

Explanation 2 is favoured because the same client got a `200 OK` moments after the `400`, so the session's baseline history was not on its own too large.

**Do not write 524,288 into the config.** Neither side's metadata is evidence of the real ceiling. The honest limit has to be measured before a number is declared.

A controlled probe was attempted and was inconclusive: both large requests returned `429 You've exceeded your subscription rate limits`. No number is claimed. The empirical ceiling remains a follow-up, and a `429` must be reported as an inconclusive probe, never as a limit.

## Gap 2: a `400` does not cascade to the group's other deployments

The live router settings are `routing_strategy: simple-shuffle`, `num_retries: 0`, `enable_pre_call_checks: true`, and an `allowed_fails_policy` that names only `RateLimitError`. There is no `fallbacks` or `context_window_fallbacks` list.

A `400` is a caller fault and is not in the retryable set, so the group's order-2 and order-3 deployments are never tried. One provider's refusal means no attempt anywhere else in the group, even when another deployment in that group might accept the request. This gap is independent of the gateway choice and belongs in the Bifrost translation notes as well.

## Follow-ups

1. Measure the real input ceiling with small, few, explicit probes. Treat a `429` as inconclusive.
2. Decide whether to declare `max_input_tokens` per deployment from that measurement, and add a test that ties the declared value to a measurement record rather than to an advertisement.
3. Decide the oversized-request policy: pre-call filtering on the measured limit, a `400` or context-window fallback path, or both. Verify the chosen behaviour on the Bifrost cutover.
