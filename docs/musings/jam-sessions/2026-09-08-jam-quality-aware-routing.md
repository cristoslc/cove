---
title: "Jam: Quality-Aware Auto-Routing for the Cove Router"
created: 2026-09-08
status: Draft
---

# Jam: Quality-Aware Auto-Routing

The most important layer, and the one LiteLLM does not have natively. Open questions over answers — this is the jam record, not a spec.

## The problem

Balancing (see [router architecture](../router-architecture-zdr-balancing.md)) picks a deployment for the model the harness asked for. Quality-aware routing goes one level up: decide whether the harness's *model choice* was even right for the request, and rewrite it when a cheaper model would do. The value at metered pricing is obvious — most router traffic is small calls (file reads, quick edits, summaries) that don't need a flagship — but the failure mode is invisible: a bad rewrite isn't an error, it's a quietly worse session.

## What the router can see at request time

From the litellm pre_call hook position:

- Requested model (the alias)
- Message count and token count
- Message shape: tool-heavy vs conversational, system prompt presence/size
- Harness identity (sleev-style headers, or model aliases that encode intent)
- Headers: streaming vs buffered

What it cannot see: whether the request is *hard*. Intent classification from the request body is guesswork. The proxy can only route on proxies-for-difficulty, and every proxy is gameable by the harness's own choice of primary model.

## Prior art in the field

- **Headroom's effort router** (source, read this session): dials *thinking effort* down when a turn is only model-resuming-after-tool-result; keeps full effort for new questions and errors. Applied on the Anthropic `/v1/messages` path only. Important: it routes *effort*, not *model* — same model, cheaper execution. This is a lower-risk knob than model rewriting because it cannot change capability, only verbosity of reasoning.
- **9Router's tier combos**: user-declared static ladders (subscription → cheap → free). Human-authored policy, not per-request inference. Works because the human accepts occasional quality dips.
- **Synthetic's `syn:` aliases**: curated quality tiers maintained upstream, not per-request.
- **DCP/Sleev**: compress context, not models — adjacent but the same philosophical family: spend less on the parts of the request that don't need it.

## Design directions (candidates, not decisions)

1. **Static per-alias ladders, model-rewriting via config** — no hook: aliases like `auto/code` that map to a hand-tuned ladder. Zero code, but no per-request intelligence. Probably too blunt.
2. **pre_call hook with cheap heuristics** — rewrite based on token count, tool presence, streaming. e.g. <4K tokens and no tools → tier-1 free model. Fast, no ML, wrong sometimes.
3. **Agent-cooperative toolkit** — Sleev's shape: expose a "route" tool the model calls itself. Highest fidelity (the model knows what it's about to do), but requires harness cooperation, which conflicts with the portability constraint.
4. **Effort-steering instead of model-rewriting** — Headroom's approach generalized: keep the requested model, dial thinking/verbosity. Capability-preserving by construction. Doesn't save tier-3→tier-1 money but saves output tokens (5× input pricing on some models).

## The eval problem (the hard part)

A router rewrite is acceptable iff the cheaper model produces equivalent session outcomes. Measuring "equivalent" needs a benchmark over real Cove sessions — and today's replay harness measures token counts, not outcome quality. Building outcome-eval (does the rewritten-model session complete the task at equal quality?) is the same shape as the test-driven work: golden sessions, graded diffs. No shortcut exists. Any auto-router built before the eval exists is flying blind.

## The relationship to the compressor

Both are "spend less on what doesn't need it" layers: compression reduces the request, quality routing reduces the model. They compose (compress then route) but also overlap — a compressed request may fit a smaller model. Sequencing thought: compress first (savings measured at 12-25%), then decide whether model-rewriting still pays. The two interact; evaluating them jointly is a trap — evaluate the compressor first, freeze it, then the router.

## Open questions for the jam

1. Are Cove sessions actually stratified? (What fraction of requests are small/cheap by token count? Measurable from the opencode store — same method as the metered-economics query.)
2. Is model-rewriting ever acceptable when the harness explicitly named a model? (Consent question: harness-said vs router-guessed.)
3. Where does the hook live — litellm pre_call custom guardrail (in-process), or the compressor proxy's pre-send stage?
4. Is effort-steering a better first tranche than model-rewriting? (Capability-preserving, zero eval risk on correctness.)
5. Does any of this survive the portability constraint, given portability was the whole reason to avoid harness-coupled solutions?

## Status

Open. No recommendation yet. Next concrete step if this jam is picked up: the stratification measurement (question 1) — it quantifies the prize with data we already have, and everything else depends on knowing it.