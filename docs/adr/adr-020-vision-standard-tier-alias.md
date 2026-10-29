# ADR-020: Vision-Led Standard Tier Alias (ADR-008 applied)

**Status:** Accepted
**Date:** 2026-10-29
**Authored-by:** DeepSeek-V4.1-Flash via bb
**Related:** ADR-008 LiteLLM Tier Routing Policy (workstation repo, `docs/adr/Active/(ADR-008)-LiteLLM-Tier-Routing-Policy/`), `docs/services/bifrost.md`, `compose/bifrost/config.json`

## Context

ADR-008 (the tier-routing policy home, in the workstation repo) fixes the
alias-naming invariant: **"Aliases lead with the modality, or with a transport
qualifier when the tier differs only by transport. The vision split keeps
image-capable models off text-only tiers, so a caller that sends images never
lands on a model that cannot read them."**

The standard tier routes to **DeepSeek V4.1 Flash**, and that model accepts
image input. That was established on 2026-10-22 in the workstation repo (a
real PNG returned its colour, and Synthetic's catalogue declares
`input_modalities: ["text", "image"]`) and re-verified on 2026-10-29 with a
live probe through the running Bifrost gateway. The alias `text:standard` is
therefore a `text:`-led name serving an image-capable model, which contradicts
ADR-008's own invariant.

ADR-008 left this naming question open at the time. The workstation CHANGELOG
recorded the fork: "whether Standard should be renamed to a `vision:`-led alias
per ADR-008 or ADR-008 amended to treat the prefix as a guaranteed floor". The
cost of the rename is that 34 bb project defaults remember `cove/text:standard`
as their model, so a rename is a migration, not an edit.

The operator has now ruled: the rename is the answer, and discovery flows
through the API/alias name.

## Decision

**Apply ADR-008's invariant.** The standard tier's canonical aliases become
`vision:standard` (streaming) and `nonstreaming:vision:standard` (the transport
variant), resolving to exactly the chains the tier served before. The former
names — `text:standard` and `nonstreaming:text:standard` — remain resolvable as
**deprecated aliases pointing at the identical chains**, so no client breaks
while they migrate.

### ADR-008 applied, not amended

The invariant is not softened; the configuration is brought into line with it.
ADR-008's rule stands as written. One consequence follows and is recorded here
so it is not left implicit: **ADR-008's own tier table, in the workstation
repo, still lists `text:standard`.** That row must change to `vision:standard`
(and `nonstreaming:text:standard` to `nonstreaming:vision:standard`) so the
policy table and the config agree. That is a workstation-lane edit; the cove
repo cannot make it. Until it lands, ADR-008's table is the stale artifact, not
the config.

### The alias name is the discovery mechanism

Bifrost's OpenAI-compatible `/v1/models` listing is **empty on this deployment**
and carries no capability field; none may be added (the config schema has no
capability or modality field, so a hand-rolled key would be an unverified
claim). The machine-readable discovery surface is the routing-rule API
(`GET /api/governance/routing-rules`), where each tier is a rule whose
`cel_expression` names the alias and whose `description` — a real, schema-defined
field shown in the dashboard's Routing Rules list — states the capability. The
alias NAME is what a caller reads: `vision:standard` says the tier reads images.

## Consequences

- `compose/bifrost/config.json` carries eleven routing rules: nine canonical
  aliases (two of them now vision-led) plus two deprecated `text:standard`
  aliases. Priorities stay unique (Bifrost requires it within a scope).
- Clients pinned to `text:standard` / `nonstreaming:text:standard` experience no
  change: the deprecated rules resolve to the identical chains.
- The deprecated-rule **removal is a later step** and requires the client
  surfaces, the 34 bb project defaults, and the LiteLLM overlay to move first
  (ordered list in `docs/services/bifrost.md`, "Alias migration").
- Two follow-ons sit outside this repo: the ADR-008 tier-table amendment above,
  and the client-surface move in the workstation lane.

## Alternatives considered

### Amend ADR-008 to treat the prefix as a floor — rejected

The operator chose the ADR's own answer. A "text: is a floor, vision may still
be present" reading would leave the discovery surface ambiguous for exactly the
caller the invariant protects: a client deciding whether it can send an image.

### Hard rename, dropping `text:standard` on merge — rejected

The failure mode is immediate and wide: 34 remembered bb project defaults, the
workstation opencode provider config, and the omp models template all name
`text:standard`. A merge-night rename 404s every one of them. Deprecated aliases
cost nothing and make the migration a client-side choice.

### Document the capability without renaming — rejected

That is the surface the operator explicitly overruled: documentation is not
discovery when the API and the alias list are what clients read.

### Add a capability field to the config — not available

Bifrost's config schema defines no capability/modality field on a model or a
routing rule. Adding an unread key would be a claim that survives because
nothing verifies it, which is the defect class this repo keeps finding. The
`description` field is used instead because it is real and rendered.
