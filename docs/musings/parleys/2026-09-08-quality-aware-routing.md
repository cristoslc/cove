# Parley: Quality-Aware Auto-Routing

## Topic

Whether and how the Cove router should rewrite model choices per request (quality-cost routing), beyond the balancing layer (see `docs/musings/router-architecture-zdr-balancing.md`). Companion jam record: `docs/musings/jam-sessions/2026-09-08-jam-quality-aware-routing.md`.

## Opening position (agent)

The router should NOT rewrite model choices initially. First tranche: effort-steering (capability-preserving, Headroom-pattern) if it survives portability review, and the stratification measurement to quantify the prize. Model-rewriting waits until an outcome-eval exists, because a wrong rewrite is a silently worse session with no error signal.

## Tension backlog

### T-1: Consent — harness-said vs router-guessed (OPEN)

The harness names a model explicitly (e.g. `ollama-cloud/glm-5.3-flash:cloud` for every opencode call — it's the config default, not a per-task judgment). So "the harness chose it" is weak evidence: most requests carry a default, not a decision. If the default is never actually *chosen*, the consent objection to router rewriting weakens. But: subagent dispatches do pick models deliberately (e.g. kimi-k3 for the recommendation task). Distinguishing "default alias" from "deliberate pick" may be possible via the harness config.

*Status: raised 2026-09-08, unresolved.*

### T-2: Stratification unknown (low-fidelity, measurable now)

What fraction of Cove router traffic is small/cheap? Same store-query method as the metered-economics work. Quantifies the prize. No parley blocker — this can run alongside.

### T-3: Eval methodology for "equivalent outcome" (high-fidelity — prototype, don't grill)

Outcome-quality benchmark over real sessions. Golden sessions, graded diffs. Shape is known (test-driven discipline) but the grading rubric for "silently worse" is the open question. Needs prototyping: run N sessions, A/B model, grade.

### T-4: Hook placement (grillable)

pre_call custom guardrail (in-process litellm) vs compressor proxy pre-send stage. Tension: compressor first, freeze, then route (sequencing rule from the jam) argues for keeping them separate; single-point-of-control argues for the compressor proxy owning both. Leans in-process litellm hook: keeps the compressor's measured state frozen.

### T-5: Portability — does model-rewriting violate it?

Rewriting happens at the router, which is harness-agnostic — portability survives. But the rewrite must not depend on harness-specific signals (opencode-only headers), or we re-couple. Constraint on the hook's signal set.

### T-6: Effort-steering scope (grillable)

Headroom's effort router is Anthropic-path-only today. OpenCode traffic is OpenAI-shaped. Does effort-steering even apply to our primary traffic? If not, the "safe first tranche" claim weakens and the choice collapses toward model-rewriting or nothing.

## Resolutions

(none yet)