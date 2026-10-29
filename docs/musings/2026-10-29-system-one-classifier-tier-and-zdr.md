---
title: "The System One classifier tier, and the decision-model ZDR landscape"
date: 2026-10-29
status: implemented
thread: thr_7ynv3bhyys
related:
  - docs/services/bifrost.md
  - compose/bifrost/config.json
  - cli/tests/test_bifrost.py
  - ADR-008 (workstation repo) and ADR-020 (this repo)
---

# The System One classifier tier, and the decision-model ZDR landscape

## The question

Can Bifrost carry a `vision:system1-classifier` (and/or `text:system1-classifier`)
tier pointing at Ollama's System One API and the Clef decision model on Ollama
Cloud? If not, what pathways exist through Cove's services? And does Ollama
provide zero data retention (ZDR) on decision models — what about OpenRouter,
and any other decision-model provider with consumer ZDR?

**Follow-up (added 2026-10-29):** is there a decision-model provider with real
ZDR that could actually be added, and what does OpenRouter charge? Answers in
Part 1b (the ZDR decision-provider shortlist) and Part 4 (OpenRouter's fees with
arithmetic).

## Answer in one paragraph

Yes, Bifrost carries it — with a shape the question did not anticipate. Bifrost
v2.3.2 has a first-class **Decisions** capability (`POST /v1/decisions`) and an
**Ollama provider that speaks System One** (`POST /v1/systemone`). The correct
change is not a fourth custom provider instance; it is the **built-in `ollama`
provider** pointed at `https://ollama.com`, plus a routing rule and an alias.
The alias must lead with the modality, so the honest name is
`vision:system1-classifier` (Clef reads images). It is a **decision tier, not a
chat tier**: it is served on `/v1/decisions`, never `/v1/chat/completions`. It
was proven with real requests through the running gateway on 2026-10-29. On ZDR:
no provider examined publishes a *decision-model-specific* retention policy, but
**Cloudflare Workers AI** does publish a contractual, consumer-terms no-retention
commitment that covers Clef, the one carryable ZDR decision provider (Part 1b);
Ollama's terms promise transient processing and no training but publish no fixed
retention window and no consumer opt-out, so the shipped tier is not a ZDR
guarantee; and OpenRouter is the only stack-reachable *gateway* with a
per-request ZDR switch, whose decision models are genuinely covered by it
(Part 4 has its fees). Details and citations below.

---

## Part 1 — Can Bifrost carry it

The claims in this part are read from Bifrost's own source at the pinned tag
(`transports/v2.3.2`, commit `a05ea20e6`) and from its docs, not inferred by
analogy.

### 1.1 What provider shapes Bifrost supports

Bifrost has two provider kinds. Built-in providers (one per vendor) and
**custom providers**, which are additional instances of a built-in base with
their own name, request allowlist, and optional path overrides. The custom
base list is closed and small:

```go
// core/schemas/bifrost.go (transports/v2.3.2)
var SupportedBaseProviders = []ModelProvider{
    Anthropic, Bedrock, Cohere, Gemini, OpenAI, HuggingFace, Replicate, Typesafe,
}
```

`ollama` is **not** in that list, and provider validation rejects an unlisted
base (`IsSupportedBaseProvider`). So a custom provider cannot use Ollama's
protocol. A custom provider *can* point at an arbitrary base URL (the three
Cove instances already do), and it *can* override request paths
(`request_path_overrides`). What it **cannot** do is invent a new
request/response schema: the conversion code is Go, fixed per base provider.
`request_path_overrides` moves the URL, not the body shape.

Bifrost's compat plugin has fixed emulations (`convert_text_to_chat`,
`convert_decision_to_responses`), but those are a closed set of
transformations, not arbitrary adapters.

### 1.2 Is the System One API OpenAI chat-completions shaped?

No. `POST /v1/systemone` is a **classification endpoint with its own contract**,
documented by Ollama as the System One API:

| | OpenAI chat completions | Ollama System One |
| --- | --- | --- |
| Path | `/v1/chat/completions` | `/v1/systemone` |
| Request body | `messages`, `tools`, `temperature`, … | `model`, `state`, `images`, `questions` |
| Questions | n/a | a named map; each is `choice`, `noul`, or `score` with `instructions`/`criteria` |
| Response | `choices[].message.content` | `answers` keyed by question name, with `choice`/`noul`/`score`, `probabilities`, `confidence`, plus `usage` |
| Streaming | yes | **not supported** |
| Tools / video / generation controls | yes | **not supported** |
| Auth | `Authorization: Bearer <key>` | same |

It differs in every structural field: request fields, response fields, no
streaming, and it is a scoring endpoint rather than a generation endpoint. A
provider cannot bridge that by URL rewrite.

### 1.3 Bifrost already has a Decisions capability

This is the finding that reframes the question. Bifrost v2.3.2 ships
`POST /v1/decisions` (Bifrost's unified decision shape), plus native drop-in
routes `POST /openai/v1/decisions` and `POST /typesafe/v1/systemone`. Providers
with the `Decisions` capability include TypeSafe, OpenAI, OpenRouter,
Cloudflare, Perplexity, **Ollama**, Azure, Databricks, vLLM, and SGLang.

The Ollama provider's implementation posts the TypeSafe-shaped body to
`/v1/systemone` and normalises the reply:

```go
// core/providers/ollama/decision.go (transports/v2.3.2)
const ollamaDecisionPath = "/v1/systemone"
// ToOllamaDecisionRequest converts a normalized decision request into
// Ollama's body ... Questions and state go through Typesafe's converter
```

### 1.4 Which provider carries Clef, and its model id

Clef is served through the **built-in `ollama` provider**, not the existing
`ollama-cloud` custom instance. Two reasons, both source-backed:

1. `ollama` is not an allowed custom base (§1.1).
2. `ollama-cloud` is an `openai`-base custom provider. Its `Decision` path
   would call `https://ollama.com/v1/decisions` with OpenAI's decision body
   (`core/providers/openai/decision.go`, `openAIDecisionsPath = "/v1/decisions"`),
   which is the wrong endpoint and the wrong shape against Ollama.

Model id on Ollama Cloud: call `ollama.com` directly with **`clef`** (the library
page says "Use `clef` when calling ollama.com directly"; `clef:cloud` is the
name for the local Ollama CLI signed in to ollama.com). `GET https://ollama.com/v1/models`
lists the cloud tag as `clef:27b`; a direct `/v1/systemone` call with `clef`
resolves upstream to `clef:27b`.

The built-in provider **requires** a per-key `ollama_key_config.url`. This is
not a decorative key: `core/utils.go` rejects an ollama key with no
`OllamaKeyConfig` (`ollama_key_config is required`) or an empty URL
(`ollama_key_config.url is required`), and live-verified 2026-10-29 the
gateway skips such a key at startup (`ollama_key_config is required, skipping
key`) and every request 400s with `no_key_supports_model`. `network_config.base_url`
is a runtime fallback in the request code but does not satisfy validation, so
both are set.

### 1.5 The plugin surface (confirmed, with a source)

Confirmed and settled: the official Bifrost image **cannot load a plugin that
would adapt a non-conforming API.**

- `transports/Dockerfile` builds with `-ldflags="-w -s … -extldflags '-static'"`
  and `-tags "sqlite_static"`. The docs state plainly that "statically linked
  binaries **cannot load Go plugins**". Go plugins need `-buildmode=plugin` and
  dynamic linking.
- The runtime's only custom-plugin loader is `SharedObjectPluginLoader`, which
  calls `plugin.Open` on a `.so` (`framework/plugins/soloader.go`,
  `framework/plugins/soplugin.go`). `transports/bifrost-http/server/plugins.go`
  wires that one loader; there is no `.wasm` branch.
- The WASM path is **deprecated** and, more decisively, its contract is
  **one-way**: "There are no host functions to call back into … A WASM plugin
  sees only what arrives in its hook input payload." A WASM plugin therefore
  cannot make an outbound HTTP call to an adapter service. Webhook-based
  plugins are advertised as "being added", i.e. not available.

So the plugin route is closed for this purpose, on the official image, today.

### 1.6 The correct alias name, with ADR-008 in hand

ADR-008: "Aliases lead with the modality." ADR-020 applied it to the standard
tier. Applied here: **Clef accepts image input**, so the correct alias is
`vision:system1-classifier`, and a `text:` one would be the mirror of the
`text:standard` defect (a name that understates the served model's modality).

Evidence Clef is multimodal, in two independent forms:

- Ollama's model page lists Clef's input as **Text, Image** for every tag
  (`clef:latest`, `clef:27b`, `clef:cloud`, `clef:27b-cloud`), and the System
  One OpenAPI `images` field says it "Requires a model with vision, such as Clef."
- A live request through this gateway on 2026-10-29: a 16×16 solid-red PNG sent
  as an `input_image` part returned `colour = red` at `0.9903` and
  `is_red = 0.9941`.

No `text:system1-classifier` alias is added. It would be resolvable and not a
lie, but it would be exactly the understating name ADR-020 removed, and it would
add a second name for one tier with no migration reason to keep it.

**ADR-008 correctness check.** The invariant is about the *name*, and the name is
the discovery mechanism. The name leads with the modality, the served model
actually accepts that modality, and the parse is verifiable: Clef reads images,
so `vision:` is honest. A caller who sends an image lands on a model that reads
it. The test suite pins the prefix and the image-input description so a future
edit cannot silently rename the tier to a `text:`-led lie, or drop the
description that carries the capability.

---

## Part 1b — A decision provider with real ZDR (the shortlist)

Two different things get conflated here, so they are separated first: a
**gateway** with a per-request ZDR switch (OpenRouter), and an **underlying
provider** whose terms commit to no retention. A switch with no qualifying
endpoint behind it is not ZDR.

### 1b.1 What OpenRouter's ZDR routing actually reaches

OpenRouter publishes its ZDR-classified endpoints as JSON each
([`https://openrouter.ai/api/v1/endpoints/zdr`](https://openrouter.ai/api/v1/endpoints/zdr),
fetched 2026-10-29). As of that fetch it lists **1,089 ZDR endpoints across
66 providers**. Decision and classification models are among them, so the
switch is not empty for this use case:

| Decision model | ZDR endpoints (providers) |
| --- | --- |
| `cloudflare/clef-flash` | Cloudflare, DeepInfra, Makora, PrimeIntellect |
| `cloudflare/clef` | Cloudflare, DeepInfra, PrimeIntellect |
| `cloudflare/clef-omni` | Cloudflare |
| `typesafe/jev-1.13`, `typesafe/jev-1.14` | TypeSafe (2) |
| `perplexity/pplx-decider-v1.2`, `-flash-v1.2` | Perplexity |
| `microsoft/microsoft-decision-1` | Azure |
| `scaledown/classify-1` | ScaleDown |

So OpenRouter's no-retention routing does reach small decision models today,
including `clef-flash` (the small, cheap one) across four providers. Two caveats
keep this from being the clean answer: the ZDR docs describe `provider.zdr` as
provider preferences on inference requests, and **whether that preference
applies to OpenRouter's alpha decisions route** (`/api/alpha/decisions`) is
unstated; and OpenRouter's classification is **OpenRouter's record of each
provider's policy**, with special agreements where the default differs (TypeSafe
jev is the example: TypeSafe itself sells ZDR as enterprise-only, but OpenRouter
classifies its endpoint ZDR).

### 1b.2 A provider with a contractual consumer retention commitment

Checking the decision models reachable from this stack against the test
(a fixed retention window or explicit no-retention, no training, and a named
abuse carve-out), on **consumer** terms rather than a policy page:

| Provider | Commitment | Kind | Abuse carve-out | Can Bifrost carry its decisions? |
| --- | --- | --- | --- | --- |
| **Cloudflare Workers AI** (Clef) | "does not retain inputs or outputs after they are no longer needed to process the request and deliver the response" | contractual (Workers AI data-usage page) | stateful features you enable; legal obligations | **yes** — built-in `cloudflare` provider, Decisions at `/accounts/{id}/ai/run/@cf/cloudflare/{model}` |
| **Ollama Cloud** (Clef) | transient processing, no fixed window | contractual but not ZDR | fraud/abuse, no window published | yes (the tier already shipped) |
| **TypeSafe** (Jev) | ZDR is enterprise-only on TypeSafe's own terms | DPA/enterprise | — | yes as a custom `typesafe`-base provider, but not on consumer terms |
| **Perplexity** (Decider) | "ZDR is available only to eligible customers … under a written agreement" | gated | — | yes as a built-in provider, but not on consumer terms |
| **DeepInfra** (hosts Clef) | "We do not log the content of your requests"; no-store/no-train by default | contractual default | none published | **no direct path** — not a Bifrost provider, and a custom `openai` base would post OpenAI's decision shape |
| **Azure** (Microsoft-Decision-1) | enterprise | enterprise | — | yes as a built-in provider, not consumer |
| **Self-hosted** (vLLM / SGLang running Clef Flash; Laya / Nimble) | no third party receives the prompt | by construction | none — it is our host | yes (`vllm/clef-flash`, `sgl/clef-flash`; Laya/Nimble as custom `typesafe` providers) |

**The one provider that is both ZDR on consumer terms and carryable by
Bifrost's Decisions path is Cloudflare Workers AI, serving Clef.** It is the
same model family the Ollama tier already uses, so the tier's name and shape do
not change; only the retention story does. The strongest retention position
overall is self-hosting, because no third party sees the prompt at all, but it
needs a GPU host and a new service, which is out of scope for a config change.

### 1b.3 Request shape, per candidate

Bifrost's Decisions capability converts one normalized request out to each
provider, so the question is which provider *base* the decision path supports:

- **System One / TypeSafe shape.** Built-in `ollama` (systemone) and
  `cloudflare` (Clef run endpoint, converted through TypeSafe's converter), plus
  **custom providers on the `typesafe` base** (how Laya and Nimble are added).
  A custom provider cannot be built on the `ollama` or `cloudflare` base.
- **OpenAI decisions shape.** The built-in `openai` provider, and custom
  providers on the `openai` base, which forward to their upstream's
  `/v1/decisions`.
- **OpenRouter.** Built-in `openrouter` provider, posting to OpenRouter's
  `/alpha/decisions` with the TypeSafe request shape
  (`core/providers/openrouter/decision.go`). Its typed request carries no
  `provider` preferences, so a per-request `zdr` flag is not expressible through
  this path without the passthrough-extra-params escape hatch, which is
  unverified for the decisions route.
- **Self-hosted.** vLLM and SGLang are built-in providers with Decisions; Laya
  and Nimble are System One servers added as custom `typesafe`-base providers.

### 1b.4 The concrete config shape, and the evidence needed first

Clef on Cloudflare is multimodal, so per ADR-008 the alias still leads with
`vision:`. (A text-only classifier, such as `nace-ai/drex-v1.5` or
`jaredpalmer/kev-4b`, could not take a `vision:` name.) The shape is a second
provider plus a ZDR-led tier:

```json
"cloudflare": {
  "keys": [{
    "name": "cloudflare-workers-ai",
    "value": "env.CLOUDFLARE_API_TOKEN",
    "models": ["clef-flash", "vision:system1-classifier"],
    "aliases": { "vision:system1-classifier": "clef-flash" },
    "cloudflare_key_config": { "account_id": "env.CLOUDFLARE_ACCOUNT_ID" },
    "weight": 1.0
  }]
}
```

with a routing rule `model == 'vision:system1-classifier'` targeting
`cloudflare/clef-flash`, and `cloudflare` added to the virtual key's
`provider_configs`. `cloudflare_key_config.account_id` is required, exactly as
`ollama_key_config.url` is for the ollama provider.

Two design points the shape forces, and both need a ruling rather than a
default:

- **Where the ZDR tier sits relative to the shipped Ollama tier.** Either the
  same alias points at Cloudflare only (ZDR by construction, and the Ollama hop
  is removed), or a separate ZDR-led alias exists beside it. A fallback from a
  ZDR tier to a non-ZDR provider would break the guarantee silently, which is
  the failure the tier exists to prevent, so a mixed chain is the wrong answer.
- **Egress.** Cloudflare Workers AI is `api.cloudflare.com` (plus the per-account
  `*.cloudflare.com` host), which is **not** on the Bifrost DNS allowlist, so
  `compose/bifrost/dnsmasq.conf` would need a fourth documented contact.

**Evidence required before writing any of it, none of which is available on this
host (1Password is signed out; no `CLOUDFLARE_API_TOKEN` or
`OPENROUTER_API_KEY` is present):**

1. A Cloudflare API token with Workers AI permission and the account ID.
2. A real `POST /v1/decisions` through Bifrost to `cloudflare/clef-flash`
   returning `routing_info.provider = "cloudflare"`, and a real image decision,
   before any alias is written.
3. A confirmation that Cloudflare's ZDR covers the Clef run endpoint, not just
   the Workers AI chat path (the data-usage page is product-wide, but the run
   endpoint is a different route).

If a Cloudflare credential cannot be obtained, the smallest thing that changes
the answer is a different ZDR endpoint carrying the same model: DeepInfra hosts
`cloudflare/clef` and `clef-flash` with no-store terms and is reachable through
OpenRouter, but not through Bifrost's own Decisions path, so it would require
OpenRouter as the transport and inherits the `provider.zdr`-on-decisions
question above.

---

## Part 2 — What pathways exist

Part 1 says Bifrost can carry it, so the "if it cannot" options are recorded for
completeness and because two of them describe real residual gaps.

### 2.1 Recommended — built-in `ollama` provider + routing rule (chosen)

Where the code lives: `compose/bifrost/config.json` (one provider block, one
routing rule, one virtual-key grant) and `cli/tests/test_bifrost.py`. This is
the smallest viable change and reuses Bifrost's own decision machinery. Cost:
one new provider, one rule, one VK grant; no new service, no new code.

What it duplicates or breaks: nothing removed. It introduces a provider name
(`ollama`) distinct from the existing custom `ollama-cloud`, which is a naming
awkwardness worth a comment in the config. It cannot be reached through
`llmproxy.cove` until cutover (the neutral endpoint still points at LiteLLM);
until then the decision endpoint is reachable at `bifrost.cove`.

Residual gap (the honest caveat): the tier is only meaningful on
`POST /v1/decisions`. A client that speaks only chat completions cannot use it.
No client on this workstation speaks `/v1/decisions` today, so the tier is
plumbing for a future caller, not a capability in use yet.

### 2.2 A thin adapter service in the Cove compose stack

An OpenAI-compatible endpoint that translates chat-completions to the System One
contract, in front of or behind Bifrost. **Rejected on the fail-loud principle.**
A chat request has no `questions` schema, so an adapter would have to invent one
(or guess a label set), and a guessed classification is worse than an error. A
translation adapter would also sit *outside* Bifrost's virtual-key boundary and
its request-logging-off posture, adding a second credential path and a new
prompt-bearing component to harden. It exists only if a chat-only client must
call a decision model, which is not the case here.

### 2.3 A Bifrost upstream feature

The ask would be a new provider base or a per-provider "systemone" conversion.
Not plausible as a near-term path: Bifrost already ships System One support for
its Ollama provider and TypeSafe base, so this is not a gap upstream would
prioritise. (If the operator wanted Cloudflare-hosted Clef — `cloudflare/clef`
is already a Bifrost Decisions provider — that is reachable today with a
Cloudflare key, no upstream change.)

### 2.4 Serve it outside Bifrost, as a Cove service

A small Cove service exposing `/v1/systemone` directly to callers. Cost: a new
container, a new nginx vhost, a new credential (the Ollama key would leave the
Bifrost boundary), its own observability, and a fourth path to the same upstream
key. It also breaks the offline-first / single-egress shape: Bifrost's DNS choke
and digest pin are the current anchors, and a second egress component recreates
a quiet-egress surface. **Rejected as strictly more surface for the same
result.**

### 2.5 Do nothing

Defensible. A decision tier with no client is inventory. The counter-argument
that carried the decision: the change is ~40 lines of config the platform
already supports, it proves the capability end to end, and it is reversible by
deleting three keys. The recommendation is to keep it, and to treat the client
surface as a separate decision.

### 2.6 Loss of the built-in-provider route is the only route at risk

`ollama_key_config is required` is a validation rule observed live; if a future
Bifrost release changes Ollama key validation, or drops the Decisions
capability, the tier breaks. The regression is loud (400 `no_key_supports_model`),
not silent.

---

## Part 3 — Zero data retention

### 3.0 Definition used here

ZDR means all three together: (a) prompts and completions are not retained
beyond in-flight processing, (b) they are never used for training, and (c) any
abuse-monitoring logging is either excluded or time-boxed and disclosed. A
provider that promises only (b), or (a) with an undisclosed abuse-log window, or
(a) only under a negotiated enterprise contract, does **not** have ZDR for a
consumer caller. A consumer plan is a self-serve agreement; an enterprise
contract is a negotiated DPA. Marketing pages and help-centre articles are not
terms of service.

### 3.1 Ollama (the serving provider for this tier)

| Claim | Wording (source) | Kind |
| --- | --- | --- |
| Cloud content is processed transiently | "we process this content transiently to provide the Service and this content is not stored beyond the time required to fulfill the request … technical measures designed to minimize retention of prompt and response content" (`ollama.com/privacy`, March 2026, §2) | contractual |
| No training | "We do not use your inputs or outputs to train AI models." (`ollama.com/terms`, May 2026, §5) | contractual |
| Not logged | "we process your prompts and responses to provide the service but do not store or log that content and never train on it" (Ollama FAQ) | help-centre |
| Decision models treated differently? | **Nothing found.** Neither the System One docs nor the Clef page states a different retention policy for decision models. | unstated |
| Consumer opt-out from retention? | No per-request or per-account ZDR switch. The only lever is disabling cloud features entirely (`OLLAMA_NO_CLOUD=1` / `disable_ollama_cloud`), which removes cloud models rather than promising ZDR. | — |
| Abuse-monitoring window | The privacy policy lists "Detect and prevent fraud or abuse" and "Enforce our Terms of Service" as purposes, but publishes **no retention window** for such logs. | unstated |

**Verdict: not a ZDR guarantee.** Ollama's position is a transient-processing
commitment with no fixed retention window, no published abuse-log limit, and no
consumer opt-out. It is close to ZDR in spirit and it is a contractual term, but
a caller relying on documented ZDR cannot cite it. Any "Ollama is ZDR" claim is
stronger than the published terms.

### 3.2 OpenRouter (the only stack-reachable gateway with a ZDR switch)

OpenRouter is explicit and contractual, and it has a real per-request control.

| Control | Behaviour (source) |
| --- | --- |
| `provider.zdr: true` | "Restrict routing to only ZDR (Zero Data Retention) endpoints." |
| `provider.data_collection: "deny"` | "use only providers which do not collect user data" |
| Account / guardrail / per-model-group enforcement | ZDR toggles per model group (Anthropic, OpenAI, Google, SpaceXAI, all other) in privacy settings or guardrails; the request flag ORs with them and cannot disable account-wide enforcement. |
| OpenRouter's own retention | "For inference content covered by OpenRouter's ZDR policy, we do not retain prompts or responses after processing, except when you explicitly choose to have us store them or when retention is needed for CSAM review, reporting, and related legal preservation." |
| What ZDR does **not** cover | "ZDR enforcement only applies to provider routing for inference requests. It does not apply to plugins and tools you choose to enable." |
| Implicit caching | Counted as **not** retention, so caching endpoints stay eligible under ZDR. |
| What happens when nothing qualifies | ZDR restricts the eligible endpoint set; if no ZDR endpoint remains for the model, the request cannot be routed under ZDR (the docs also warn a provider whose endpoint-specific policy differs from its default "may not be available if 'ZDR Only' is enabled"). |
| New wrinkle (announced Oct 27, 2026) | OpenRouter will screen **all** inference requests, **including ZDR traffic**, for CSAM; flagged content may be retained for review/reporting. This is a carve-out to ZDR itself. |

**Verdict: contractual ZDR on consumer terms, with named carve-outs.** It is the
strongest *gateway* option available to this stack, and its decision models are
genuinely covered (Part 1b.1 shows the ZDR endpoint list includes them), but it
is a *gateway* control: it constrains which upstream endpoints are eligible, so
the guarantee is only as good as each provider's declared policy. Note also that
OpenRouter is not currently in the Cove stack; adding it is new surface (key,
egress allowlist, provider entry).

### 3.3 Other providers, especially those reachable or plausibly reachable

| Provider | No-retention position | Training | Kind | Consumer usable? |
| --- | --- | --- | --- | --- |
| **Synthetic** (`api.synthetic.new`, the primary provider) | "We do not store model prompts or completions from the API without your explicit consent … once they are completed such data is deleted" (privacy policy) | Contractually barred (ToS §3.4) | contractual, API-only | yes, on by default |
| **Cloudflare** (Clef's creator; Workers AI) | "For standard inference requests that do not invoke a stateful feature, Cloudflare does not retain inputs or outputs after they are no longer needed" | "does not use Customer Content processed by Workers AI to train AI models" | contractual | yes — **but only when Cloudflare serves the model**; the shipped Clef tier is served by Ollama, so this does not cover it. Cloudflare is the one carryable ZDR decision provider (Part 1b) |
| **TypeSafe** | "as long as reasonably necessary"; no fixed period published | Not on Input | ZDR is **enterprise/DPA-only** ("fill out the support request form") | no |
| **Perplexity** (pplx-decider) | "Zero Data Retention is not default … available only to eligible customers … under a written agreement" | No training by default (API ToS) | gated | no |
| **OpenAI** (gpt-6-luna decisions) | "retained for up to 30 days" abuse monitoring by default; ZDR by approval ("subject to prior approval by OpenAI") | No training by default | approval-gated | no |
| **Google Gemini API** | Paid: "logs prompts and responses for a limited period" for abuse; free tier trains on content | Free: yes; paid: no | paid = DPA-backed | partly (paid tier) |
| **Groq** | "By default, Groq does not retain customer data for inference requests"; a 30-day reliability/abuse log you can switch off | barred by contract | self-serve setting, all customers | yes |
| **Cerebras** | "We do not retain inputs and outputs associated with our … inference … Services" | no | contractual default | yes |
| **DeepInfra** | "We do not log the content of your requests" | no (except Google/Anthropic passthroughs) | contractual default | yes |
| **Baseten** | "does not store model inputs, outputs, or weights by default" for synchronous inference | no | contractual default | yes |
| **Fireworks AI** | "Zero Data Retention by default … for any open models" | no | default for open models; account-wide enforcement is enterprise | yes (open models) |
| **Together AI** | Stores prompts by default; ZDR is an org switch | opt-in only | setting, off by default | yes, but not ZDR by default |
| **Nebius** | Stores inputs/outputs by default for speculative decoding; ZDR is an account switch | no | setting, off by default | yes, but not ZDR by default |
| **Mistral** | 30 rolling days for abuse "unless zero data retention is activated" | opt-out | 30-day default + ZDR option | partly |
| **xAI** | 30 days for auditing by default; ZDR is a self-serve team setting | no | setting | yes |
| **Moonshot / Kimi** | contract retains "while your account is active"; help-centre says no training, contract says the opposite unless enterprise | conflicting | **unknown** | unknown |
| **Z.ai / GLM** | Individual: retained while account active; DPA no-storage clause is enterprise-context | "reserve the right to process any User Content to improve our existing Services" | marketing/DPA split; no consumer opt-out found | unknown |

Two of these matter most to this stack. **Synthetic** — the primary provider for
every chat tier — has an API-only, contractual no-store/no-train term, which is
the strongest position here and covers the chat ladder. **Cloudflare** publishing
contractual ZDR for Workers AI is real, but it governs Cloudflare's serving of
Clef, not Ollama's, so it does **not** transfer to the shipped tier; it is
instead the basis of the ZDR decision tier proposed in Part 1b.

### 3.4 ZDR for decision models specifically

No provider examined publishes a decision-model-*specific* retention policy. The
retention statements are per-service or per-account, so "decision models get
ZDR" as a category does not exist; what exists is a product-wide term that
happens to cover a decision model. **Cloudflare Workers AI is that case**: its
ZDR commitment is written for Workers AI as a product, and Clef runs on Workers
AI as a decision model, so the decision model is covered by a term that was
never written about decision models. Anyone claiming a *decision-model-specific*
guarantee is extrapolating; if that distinction matters for a contract, it should
be asked of each vendor in writing rather than read from a page.

---

## Part 4 — OpenRouter's charges, with numbers

Fee lines, from OpenRouter's own pages (fetched 2026-10-29; the platform-fee
structure is dated on the announcement and on the pricing page):

| Line | Value | Applies to us? | Source |
| --- | --- | --- | --- |
| Platform fee on credit **purchases** | 5.5% of the order, **$0.80 minimum**, on non-crypto payments (5.0% flat, no minimum, on crypto) | yes, only when topping up credits | announcement "Simplifying Our Platform Fee" (6/9/2025, updated 6/11/2026); pricing page |
| Inference markup | none; "Inference is billed at each provider's list price on every plan … never on individual requests" | no markup | pricing page FAQ |
| Per-request or per-token surcharge | none beyond the provider's listed token price | no | pricing page FAQ; "How are tokens billed?" |
| Minimum **purchase** amount | $5 minimum, $25,000 maximum per transaction | yes when buying credits | Terms of Service |
| **BYOK** | provider bills you directly; Standard includes $25,000 of list-price inference per month with no OpenRouter fee, then 5% of list price | effectively no fee at our volume | pricing page; BYOK docs |
| ZDR / data-policy routing | no charge; "Zero Data Retention routing is available on every plan", data-policy routing is a Standard feature | no charge | pricing page (Privacy FAQ, plan table) |
| Failed or fallback attempts | not billed; "you pay only for the run that answers" | n/a | pricing page FAQ |
| Streaming | same price | n/a | pricing page FAQ |
| Business plan | 8% platform fee on credit purchases | only if upgraded to Business | pricing page plan table |

**Is there a minimum charge per request that dominates the token price?** No.
Every decision model on OpenRouter lists `completion = 0` and `request = null`
in the models API, so a decision call is billed in **input tokens only**, at the
listed per-million rate, with no per-call floor. The only minimum is the $0.80
floor on a **credit purchase**, which is a platform fee on a top-up, not a
per-call charge. Its effect is amortized: $0.80 is 5.5% of a $14.55 purchase, so
below a $14.55 top-up the floor binds (a $5 purchase pays $0.80, about 16%), and
at or above it the fee is exactly 5.5%.

### Arithmetic

Assumption: **300 input tokens per decision call and 0 output tokens**, which is
the shape of the calls this tier serves. OpenRouter's own examples are in the
same range (289 input tokens for a Clef Flash image call, 332 for a Clef text
call), and my live probe on the Ollama tier used 312. So 1,000 calls is 0.3M
input tokens.

| Model (ZDR endpoint provider) | prompt $/M | $ per 1,000 calls | incl. 5.5% credit fee |
| --- | --- | --- | --- |
| `cloudflare/clef-flash` (Cloudflare, PrimeIntellect) | 0.038 | $0.0114 | $0.0120 |
| `cloudflare/clef-flash` (DeepInfra) | 0.019 | $0.0057 | $0.0060 |
| `cloudflare/clef-flash` (Makora) | 0.018 | $0.0054 | $0.0057 |
| `cloudflare/clef-omni` (Cloudflare) | 0.15 | $0.0450 | $0.0475 |
| `cloudflare/clef` (Cloudflare, PrimeIntellect) | 0.24 | $0.0720 | $0.0760 |
| `cloudflare/clef` (DeepInfra) | 0.192 | $0.0576 | $0.0608 |
| `typesafe/jev-1.14` | 0.042 | $0.0126 | $0.0133 |
| `perplexity/pplx-decider-flash-v1.2` | 0.01 | $0.0030 | $0.0032 |
| `perplexity/pplx-decider-v1.2` | 0.02 | $0.0060 | $0.0063 |
| `scaledown/classify-1` | 0.04 | $0.0120 | $0.0127 |
| `microsoft/microsoft-decision-1` | 0.042 | $0.0126 | $0.0133 |

The same calls cost **the same per token through OpenRouter as direct from the
provider** (no markup): Cloudflare's own published rates for these models are
`@cf/cloudflare/clef-flash` $0.038/M, `clef` $0.24/M, `clef-omni` $0.15/M, and
OpenRouter's Cloudflare endpoints list the identical figures.

**BYOK.** Route through OpenRouter with your own Cloudflare key and the Cloudflare
bill is $0.0114 per 1,000 calls (the Cloudflare rate in the table above), while
OpenRouter charges nothing until $25,000 of list-price inference in a month. At
1.14 cents per thousand calls that allowance is about 2.19 billion calls per
month, so the OpenRouter fee is effectively $0 for this tier.

**Direct, with no gateway in between.** Cloudflare Workers AI bills in neurons at
$0.011 per 1,000 neurons, and its free allocation is 10,000 neurons per day.
`clef-flash` is 3,455 neurons per million input tokens, so the free allocation
covers about 2.9M input tokens per day, or roughly **9,650 decision calls per day
at 300 tokens for $0**. Past that, `clef-flash` is $0.0114 per 1,000 calls. So a
Cloudflare-backed ZDR decision tier is both the strongest retention position
among the hosted options and free at the volume this stack would generate.

---

## Evidence table

| # | Claim | Source |
| --- | --- | --- |
| 1 | Bifrost custom-provider base list excludes `ollama`; validation rejects unlisted bases | `core/schemas/bifrost.go`, `core/utils.go` (`IsSupportedBaseProvider`), `transports/bifrost-http/lib/config.go` — tag `transports/v2.3.2` |
| 2 | Custom providers can set an arbitrary base URL and request-path overrides, but not a new schema | `core/schemas/provider.go` (`CustomProviderConfig`), `core/providers/utils/utils.go` (`GetRequestPath`), docs `/providers/custom-providers` |
| 3 | System One is `POST /v1/systemone` with `state`/`questions`, no streaming, no tools | Ollama docs `/api/systemone` (OpenAPI); docs `/capabilities/decision` |
| 4 | Bifrost has first-class Decisions: `/v1/decisions`, `/openai/v1/decisions`, `/typesafe/v1/systemone`; provider matrix row "Decisions" | Bifrost docs `/quickstart/gateway/decisions`, `/providers/supported-providers/overview`; `core/schemas/decision.go` |
| 5 | The Ollama provider posts `/v1/systemone` and reuses the TypeSafe converter | `core/providers/ollama/decision.go`, `ollama.go` — v2.3.2 |
| 6 | The `openai`-base decision path is `/v1/decisions` with OpenAI's body | `core/providers/openai/decision.go` — v2.3.2 |
| 7 | Clef model id is `clef` when calling ollama.com directly; cloud tag `clef:27b` | Ollama library page `/library/clef`; live `GET https://ollama.com/v1/models` |
| 8 | Clef reads images (Text, Image input; "requires a model with vision, such as Clef") | Ollama `/library/clef`; System One OpenAPI `images` field |
| 9 | Official image is statically linked and cannot load Go plugins | `transports/Dockerfile` (`-extldflags '-static'`), Bifrost docs `/plugins/building-dynamic-binary` |
| 10 | Only a `.so` loader is wired; WASM is deprecated and one-way (no host functions → no outbound HTTP) | `framework/plugins/soloader.go`, `transports/bifrost-http/server/plugins.go`, docs `/plugins/writing-wasm-plugin` |
| 11 | `ollama_key_config.url` is required per key (validation), not just a runtime fallback; absent → key skipped, request 400 `no_key_supports_model` | `core/utils.go` (`schemas.Ollama` case), plus live gateway log + response 2026-10-29 |
| 12 | Tier serves a text decision and an image decision through the gateway | Live `POST /v1/decisions` 2026-10-29 (records below) |
| 13 | Aliases lead with the modality | ADR-008 (workstation repo); ADR-020 (this repo) |
| 14 | Ollama: transient processing, no training, no fixed retention window, no consumer opt-out | `ollama.com/privacy` (Mar 2026 §2), `ollama.com/terms` (May 2026 §5), Ollama FAQ |
| 15 | OpenRouter: `provider.zdr`, `data_collection: deny`, per-model-group ZDR, ZDR scope excludes tools, OpenRouter's own retention with CSAM carve-out | `openrouter.ai/docs/guides/features/zdr`, `/docs/guides/routing/provider-selection`, `/docs/features/privacy-and-logging` |
| 16 | Synthetic: API no-store/no-train, contractual | `synthetic.new/policies/privacy`, `/policies/terms-of-service` |
| 17 | Cloudflare Workers AI: ZDR for standard inference, no training (Workers AI only) | `developers.cloudflare.com/workers-ai/platform/data-usage` (last updated 2026-10-16) |
| 18 | TypeSafe ZDR is enterprise-only; Perplexity ZDR is not default; OpenAI 30-day default with approval-gated ZDR; Gemini free tier trains; Groq/Cerebras/DeepInfra/Baseten/Fireworks defaults; Together/Nebius off by default | Vendor legal/docs pages named in §3.3 |
| 19 | OpenRouter's ZDR-classified endpoint set is published as JSON: 1,089 endpoints across 66 providers, and it includes decision models (Clef on 3-4 providers, Jev, the Perplexity Deciders, Microsoft-Decision-1, ScaleDown Classify-1) | `openrouter.ai/api/v1/endpoints/zdr` (fetched 2026-10-29) |
| 20 | Cloudflare is a built-in Bifrost provider with Decisions on `/accounts/{id}/ai/run/@cf/cloudflare/{model}`; `cloudflare_key_config.account_id` is required; Clef/Clef-Flash convert through TypeSafe's converter and take images | Bifrost docs `/providers/supported-providers/cloudflare`; `core/providers/cloudflare/decision.go` — v2.3.2 |
| 21 | Cloudflare's Workers AI pricing: $0.011 per 1,000 neurons, 10,000 free neurons/day; `@cf/cloudflare/clef-flash` $0.038/M input tokens, `clef` $0.24/M, `clef-omni` $0.15/M, all input-only | `developers.cloudflare.com/workers-ai/platform/pricing` (last updated 2026-10-20) |
| 22 | OpenRouter's fee structure: 5.5% on credit purchases with a **$0.80 minimum** (non-crypto; 5.0% flat on crypto), no markup and no per-request charge, credit purchase $5 min / $25,000 max, Business 8% | pricing page; announcement "Simplifying Our Platform Fee" (6/9/2025, updated 6/11/2026); Terms of Service |
| 23 | OpenRouter BYOK: Standard/Business include $25,000 of list-price inference per month with no fee, then 5% of list price | pricing page; BYOK docs |
| 24 | OpenRouter's decision models list as 33 entries with `completion = 0` and `request = null`, so a decision call is billed in input tokens only with no per-call floor | `openrouter.ai/api/v1/models?output_modalities=decisions` (fetched 2026-10-29) |
| 25 | Bifrost's OpenRouter decision path posts to `/alpha/decisions` with the TypeSafe request shape and carries no `provider` preferences | `core/providers/openrouter/decision.go` — v2.3.2 |

---

## The change set

Smallest viable change (implemented in this PR):

1. `compose/bifrost/config.json` — add a built-in `ollama` provider
   (`network_config.base_url` and the required key-level
   `ollama_key_config.url` both `https://ollama.com`; key `env.OLLAMA_API_KEY`;
   allowlist `["clef", "vision:system1-classifier"]`; alias
   `vision:system1-classifier → clef`).
2. `compose/bifrost/config.json` — one routing rule
   (`cel_expression: model == 'vision:system1-classifier'` → `ollama/clef`, no
   fallbacks, priority 12) and one virtual-key provider grant for `ollama`.
3. `cli/tests/test_bifrost.py` — pin the tier, the provider shape, the required
   key config, the no-fallback decision, and a live decision smoke.
4. `docs/services/bifrost.md`, `CHANGELOG.md`, `docs/test-coverage-matrix.yaml`.

No DNS change (ollama.com was already allowlisted). No new credential. No new
service.

### Follow-up (2026-10-29): the ZDR tier is a proposal, not a change

The Part 1b ZDR shortlist adds a second, **credential-gated** option: a Clef
tier served by Cloudflare Workers AI, whose no-retention term is contractual on
consumer terms. It is deliberately **not** implemented in this PR. Writing it
needs a Cloudflare API token and account ID, none of which exists on this host,
and the standing rule is that no alias points at a provider path that has not
answered a real request. The exact config shape is in §1b.4; the four pieces of
evidence the tier needs before it is written are listed there too. The
recommendation for the shipped tier is unchanged; the recommendation for a ZDR
tier is "build it once a Cloudflare credential and a verified Clef run-endpoint
call exist", and the alternative if no credential appears is the OpenRouter
route in Part 4, whose ZDR-on-the-decisions-route behaviour is still unknown.

The self-hosted option named in §1b.2 was assessed for hardware feasibility against the fleet's actual boxes: see [2026-10-29-self-hosted-zdr-decision-tier-hardware-feasibility.md](2026-10-29-self-hosted-zdr-decision-tier-hardware-feasibility.md).

---

## Live verification record (2026-10-29)

Upstream, direct: `GET https://ollama.com/v1/models` → 200; `POST
https://ollama.com/v1/systemone` (`model: "clef"`, one `noul` question) → 200
`{"model":"clef","answers":{"says_hello":{"type":"noul","noul":0.9874}}}`
(the Ollama Cloud key already on this host, from the workstation projection).

Through the running Bifrost gateway, with the gateway-generated client virtual
key:

- `GET /v1/models` → 200, 22 entries, including
  `ollama/vision:system1-classifier` and `ollama/clef`.
- `POST /v1/decisions`, `model: "vision:system1-classifier"`, one `choice`
  question → 200, `label = bug` (`0.977`), `routing_info = {"provider":
  "ollama", "model": "clef", "key": "ollama-cloud-systemone",
  "requested_model": "vision:system1-classifier"}`.
- `POST /v1/decisions` with a 16×16 solid-red PNG as an `input_image` part →
  200, `is_red = 0.9941`, `colour = red` (`0.9903`).

The live config (`~/Documents/cove-data/bifrost/config.json`) was backed up to
`config.json.bak-20261029-165211-system1` before this change was applied, and
then updated to match the branch config. Restoring the backup reverts the live
gateway to the pre-change state.

---

## Unknowns (explicit)

1. **Ollama's abuse-monitoring retention window.** The privacy policy names
   fraud/abuse and ToS enforcement as purposes but publishes no log retention
   period. Unstated, not "zero".
2. **Whether Ollama Cloud is under any ZDR addendum** for the operator's plan.
   No published consumer ZDR document exists; an enterprise agreement may
   differ and is not visible here.
3. **Decision-model-specific retention, at any provider.** No provider examined
   distinguishes decision models. Unstated everywhere.
4. **OpenRouter's ZDR switch on the decisions route.** Resolved in part
   (2026-10-29): the ZDR endpoint list is authoritative and **does** include
   decision models, so the switch has somewhere to route. Still open: the ZDR
   docs describe `provider.zdr` as provider preferences on inference requests,
   and whether that preference is honoured on OpenRouter's alpha decisions route
   (`/api/alpha/decisions`) is unstated; separately, Bifrost's OpenRouter
   decision request carries no `provider` object, so a per-request flag is not
   expressible through that path without the passthrough-extra-params hatch.
   Both need a live check with an OpenRouter key.
5. **No Cloudflare or OpenRouter credential on this host.** 1Password is signed
   out and no `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, or
   `OPENROUTER_API_KEY` is present in the deployed `.env` or the workstation
   secrets. The ZDR decision tier in Part 1b is therefore a shape and an
   evidence list, not a built and proven tier.
6. **Whether Cloudflare's ZDR covers the Clef run endpoint.** The Workers AI
   data-usage commitment is product-wide and Clef runs on Workers AI, but the
   decision call travels the `/ai/run/@cf/cloudflare/{model}` route rather than
   the chat route; that it is covered is a reasonable reading, not a quoted one.
7. **Bifrost's decision path against Cloudflare, unproven.** Bifrost's cloudflare
   provider is documented and present in the source, but no real decision
   request has been made through it here, so the `routing_info.provider =
   "cloudflare"` evidence the tier would need does not exist yet.
8. **No client speaks `/v1/decisions` today.** The tier is proven at the gateway,
   not consumed by a caller. Whether a caller wants it is a separate decision.
9. **`bifrost.cove` vs `llmproxy.cove` reachability.** The decision endpoint is
   reachable at `bifrost.cove` (admin surface) now; it would ride
   `llmproxy.cove` only after the LiteLLM cutover flips the product-swap line.
10. **Moonshot and Z.ai consumer positions** resolve to "unknown": their own
    pages conflict (Moonshot) or split contractual terms from marketing (Z.ai).
11. **Bifrost version drift.** This was read and proven at `v2.3.2`. A future
    release could change Ollama key validation or the Decisions surface.
