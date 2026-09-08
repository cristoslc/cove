---
title: "Spike: LiteLLM Native Headroom Guardrail (v1.92+)"
created: 2026-09-08
status: Draft
---

# Spike: LiteLLM Native Headroom Guardrail (v1.92+)

Follow-up to the [K3 certified musing addendum](./2026-09-08-headroom-k3-recommendation.md). Purpose: mechanically verify the native `headroom` guardrail — does LiteLLM ≥1.92 + a local Headroom proxy actually compress agent traffic, without any real provider?

## Setup

Isolated venv (Python 3.13, `litellm[proxy]` 1.100.0 stable, `headroom-ai[proxy]` 0.37.0), three local processes:

- **Mock OpenAI upstream** on `:9099` — records per-request char counts, returns fixed `ok` response. No provider keys anywhere.
- **Headroom proxy** on `:4411` (`headroom proxy --port 4411`) — the compression service.
- **LiteLLM proxy** on `:4410` with `config.yaml`: one model (`spike-model` → mock upstream), one guardrail (`guardrail: headroom`, `mode: pre_call`, `api_base: http://127.0.0.1:4411`).

## Results

### 1. Guardrail loads and runs — confirmed (stable release)

The `headroom` guardrail is in the 50-guardrail initializer registry on **stable 1.100.0** (the dev-release `ValueError` from BerriAI discussion #31816 does not reproduce on stable). With the request explicitly carrying `"guardrails": ["headroom-compression"]` (or with default-on, below), the full pre_call path executes and compression is applied.

**Gotcha worth its own ADR note:** `default_on: true` must live **inside `litellm_params`**, not at the guardrail-entry level. The docs show it at entry level; the schema (`LitellmParams.default_on`) and the working config are:

```yaml
guardrails:
  - guardrail_name: headroom-compression
    litellm_params:
      guardrail: headroom
      mode: pre_call
      api_base: http://127.0.0.1:4411
      default_on: true
```

With `default_on` misplaced at entry level, the guardrail silently never runs — `should_run_guardrail ... self.default_on= False`, no header, no error. This is the exact failure mode "a misconfigured guardrail looks like nothing happened."

### 2. End-to-end verification — confirmed

```
x-litellm-applied-guardrails: headroom-compression
```

Headroom's own savings ledger confirmed 9 compress calls from LiteLLM traffic (2,500 tokens saved across the session). The mock upstream received the compressed payload: a 17,200-char tool message arrived as 15,199 chars (11.6% smaller) in the four-message case. LiteLLM's fail-open contract verified too: with Headroom stopped, the request **fails with HTTP 502** (`Headroom compression service unreachable`) — it does *not* silently forward uncompressed as the sidecar architecture did. This is a **behavioral change vs Cove's current sidecar setup**: the musing's fail-open assumption does not hold for the native guardrail.

### 3. Compression content-router caveat — important for Cove's workload

The July musing's headline claim ("AST-aware compression of tool outputs") did **not** reproduce for `role: "tool"` messages. Direct `/v1/compress` tests:

| Payload shape | Result |
|---|---|
| Single `user` message, 17.2K chars repetitive text | compressed: 4,308 → 3,808 tokens (`router:text:0.88`) |
| Single `tool` message, same text | **noop** (`router:noop`, byte-identical) |
| `user`+`tool`+`assistant` rows | **noop** on all rows |

The compression router keys off **message role**, not content shape: `user`-role prose gets `router:text`; `tool`/`assistant`-role rows get `router:noop`. Since OpenCode's dominant token weight is tool results (file reads, diffs, grep output — all `role: "tool"` under OpenAI-compatible traffic), the realized savings on Cove's actual workload may be far below the 60-95% headline, which appears to be measured on user-embedded content. This needs an A/B on real OpenCode sessions before any pin bump.

Also confirmed: system messages, the last user message, and the last assistant message are structurally protected from compression (correct — that's the live instruction).

## Verdict

The native guardrail is **real, stable, and mechanically verified end-to-end** — the A-path (litellm ≥1.92 + guardrail block, retire sidecar) is technically sound. Two open items gate adoption:

1. **Savings on tool-role traffic are unproven** — the content router no-ops on `role: "tool"` in this spike. Measure on real OpenCode sessions before crediting any token savings.
2. **Fail-open → fail-closed change** — proxy-down now 502s agent traffic. Decide whether that is acceptable (or wire LiteLLM fallbacks/`num_retries` around it) before retiring the sidecar.

**Certified:** A-path feasible, confidence medium — blocked on tool-role savings measurement, not on integration mechanics.

**Update same day:** the measurement ran ([real-session replay](./2026-09-08-spike-real-session-replay.md)) — **6.3%** on actual OpenCode tool traffic, not 60-95%. Adoption verdict revised in that follow-up.

Environment: `/var/folders/.../opencode/spike-litellm-headroom/` (ephemeral; config inline above is the complete working setup).